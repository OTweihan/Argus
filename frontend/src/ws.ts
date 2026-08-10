import type { TaskEvent } from "./types";
import { request } from "./api/client";
import { getApiToken } from "./auth";

type EventHandler = (event: TaskEvent) => void;
type StatusHandler = (
  status: "connected" | "disconnected" | "error" | "reconnecting" | "reconnected",
) => void;

// 后端 WS_KEEPALIVE_SECONDS = 30，前端以 2.5 倍间隔判定断连
const HEARTBEAT_TIMEOUT_MS = 30_000 * 2.5;
const HEARTBEAT_CHECK_INTERVAL_MS = 10_000;

function wsBaseUrl(): string {
  const explicit = import.meta.env.VITE_ARGUS_WS_BASE;
  if (explicit) return String(explicit).replace(/\/$/, "");
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/argus/api`;
}

export class TaskEventStream {
  private socket: WebSocket | null = null;
  private endpoint = "";
  private reconnectTimer: number | null = null;
  private heartbeatTimer: number | null = null;
  private lastMessageTime = 0;
  private reconnectAttempt = 0;
  private manuallyClosed = false;
  private lastSequence: number | undefined = undefined;
  private wsTicketPromise: Promise<string | null> | null = null;
  private socketGeneration = 0;
  private readonly handlers = new Set<EventHandler>();
  private readonly statusHandlers = new Set<StatusHandler>();

  onEvent(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  connect(taskId?: string): void {
    const suffix = taskId ? `/ws/tasks/${encodeURIComponent(taskId)}` : "/ws/tasks";
    const endpoint = `${wsBaseUrl()}${suffix}`;
    if (this.socket && this.endpoint === endpoint && this.socket.readyState <= WebSocket.OPEN) {
      return;
    }
    this.clearReconnectTimer();
    this.manuallyClosed = false;
    this.closeSocket();
    this.endpoint = endpoint;
    void this.openSocket(endpoint, this.lastSequence);
  }

  close(): void {
    this.manuallyClosed = true;
    this.clearReconnectTimer();
    this.stopHeartbeat();
    this.endpoint = "";
    this.closeSocket();
  }

  private async openSocket(endpoint: string, sinceSeq?: number): Promise<void> {
    const generation = ++this.socketGeneration;
    const url = new URL(endpoint);
    if (sinceSeq !== undefined) url.searchParams.set("sinceSeq", String(sinceSeq));
    const token = getApiToken();
    if (token) {
      // 不把长期 Token 放进 WebSocket query（会进入反代/接入日志）：先用 Bearer
      // 换取短时、单次 ticket，再用 ticket 建立连接。拿不到 ticket（服务端未启用
      // 鉴权/已下线）时回退为不带凭据连接，由后端决定放行或 1008 拒绝。
      const ticket = await this.requestWsToken();
      // ticket 换取期间可能已 close() 或切到别的端点：用 generation + endpoint
      // 双重守卫防止创建陈旧的 socket。
      if (
        this.manuallyClosed ||
        this.endpoint !== endpoint ||
        generation !== this.socketGeneration
      ) {
        return;
      }
      if (ticket) url.searchParams.set("token", ticket);
    }
    const socket = new WebSocket(url.toString());
    this.socket = socket;
    this.lastMessageTime = Date.now();
    this.startHeartbeat();

    socket.addEventListener("open", () => {
      if (this.socket !== socket || this.endpoint !== endpoint) return;
      const isReconnect = this.reconnectAttempt > 0;
      this.reconnectAttempt = 0;
      this.emitStatus(isReconnect ? "reconnected" : "connected");
    });
    socket.addEventListener("close", () => {
      if (this.socket === socket) {
        this.socket = null;
      }
      if (this.endpoint !== endpoint) return;
      this.emitStatus("disconnected");
      if (!this.manuallyClosed) {
        this.scheduleReconnect(endpoint);
      }
    });
    socket.addEventListener("error", () => {
      if (this.socket !== socket || this.endpoint !== endpoint) return;
      this.emitStatus("error");
    });
    socket.addEventListener("message", (message) => {
      if (this.socket !== socket || this.endpoint !== endpoint) return;
      this.lastMessageTime = Date.now();
      try {
        const event = JSON.parse(String(message.data)) as TaskEvent;
        // 过滤掉系统心跳事件，不上抛给业务 handler
        if (event.eventType === "system.keepalive") {
          return;
        }
        // 跟踪最新 sequence，供重连时部分回放
        if (event.sequence !== undefined) {
          this.lastSequence = event.sequence;
        }
        this.handlers.forEach((handler) => handler(event));
      } catch {
        this.handlers.forEach((handler) =>
          handler({ eventType: "system.error", data: { message: "WebSocket 消息解析失败" } }),
        );
      }
    });
  }

  private closeSocket(): void {
    if (this.socket && this.socket.readyState < WebSocket.CLOSING) {
      this.socket.close();
    }
    this.socket = null;
  }

  /** 用 Bearer Token 换取短时单次 WebSocket ticket；失败返回 null。 */
  private async requestWsToken(): Promise<string | null> {
    if (!this.wsTicketPromise) {
      this.wsTicketPromise = request<{ token?: string }>("/ws/token", { method: "POST" })
        .then((body) => body?.token ?? null)
        .catch(() => null)
        .finally(() => {
          this.wsTicketPromise = null;
        });
    }
    return this.wsTicketPromise;
  }

  private emitStatus(
    status: "connected" | "disconnected" | "error" | "reconnecting" | "reconnected",
  ): void {
    this.statusHandlers.forEach((handler) => handler(status));
  }

  private scheduleReconnect(endpoint: string): void {
    this.clearReconnectTimer();
    this.emitStatus("reconnecting");
    const delayMs = Math.min(1000 * 2 ** this.reconnectAttempt, 15000);
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (this.manuallyClosed || this.endpoint !== endpoint) return;
      void this.openSocket(endpoint, this.lastSequence);
    }, delayMs);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  // ── 心跳检测 ──────────────────────────────────────────────
  // 后端每 30s 发 system.keepalive；前端若超过 75s 未收到任何消息
  // 则认为连接已静默断开，主动触发重连。
  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.lastMessageTime = Date.now();
    this.heartbeatTimer = window.setInterval(() => {
      if (this.manuallyClosed) {
        this.stopHeartbeat();
        return;
      }
      if (Date.now() - this.lastMessageTime > HEARTBEAT_TIMEOUT_MS) {
        // 静默断开：直接关 socket，让 close 事件处理器触发重连
        if (this.socket && this.socket.readyState < WebSocket.CLOSING) {
          this.socket.close();
        }
      }
    }, HEARTBEAT_CHECK_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }
}
