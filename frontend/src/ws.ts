import type { TaskEvent } from "./types";
import { request } from "./api/client";
import { getApiToken } from "./auth";

type EventHandler = (event: TaskEvent) => void;
type StatusHandler = (
  status: "connected" | "disconnected" | "error" | "reconnecting" | "reconnected",
) => void;

/** 服务端 `system.replay_gap` 携带的缺口信息。 */
export interface ReplayGapInfo {
  reason: "epoch_changed" | "since_seq_out_of_window";
  streamEpoch: string;
  oldestSequence: number;
  currentSequence: number;
  requestedSinceSeq?: number;
  previousEpoch?: string;
  message?: string;
}

// 后端 WS_KEEPALIVE_SECONDS = 30，前端以 2.5 倍间隔判定断连
const HEARTBEAT_TIMEOUT_MS = 30_000 * 2.5;
const HEARTBEAT_CHECK_INTERVAL_MS = 10_000;
// 重连退避上限（毫秒）。指数退避上限到 15s，再加 jitter 错开多个控制台同时恢复连接。
const RECONNECT_MAX_DELAY_MS = 15_000;

function wsBaseUrl(): string {
  const explicit = import.meta.env.VITE_ARGUS_WS_BASE;
  if (explicit) return String(explicit).replace(/\/$/, "");
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/argus/api`;
}

/** 指数退避 + 随机 jitter，避免服务恢复瞬间大量控制台同时重连。 */
export function reconnectDelayMs(attempt: number): number {
  const base = Math.min(1000 * 2 ** attempt, RECONNECT_MAX_DELAY_MS);
  // 50%–100% 区间抖动（full jitter 的一半）：既保留退避趋势，又分散重连时刻。
  return Math.round(base * (0.5 + Math.random() * 0.5));
}

/** 把 system 事件 data 里的数值安全转成 number，非法时回退默认值。 */
function toNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
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
  /** 当前连接确认的进程级事件流纪元（来自 system.ready.streamEpoch）。 */
  private streamEpoch: string | undefined = undefined;
  private wsTicketPromise: Promise<string | null> | null = null;
  private socketGeneration = 0;
  private readonly handlers = new Set<EventHandler>();
  private readonly statusHandlers = new Set<StatusHandler>();
  private readonly replayGapHandlers = new Set<(info: ReplayGapInfo) => void>();
  /** system.replay_gap 已上报、等待 system.ready 消费标记：避免同一次缺口重复上报。 */
  private gapPendingThisReady = false;

  onEvent(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  /** 服务端判定回放存在缺口（sinceSeq 超窗 / 服务重启 epoch 变化）时通知。 */
  onReplayGap(handler: (info: ReplayGapInfo) => void): () => void {
    this.replayGapHandlers.add(handler);
    return () => this.replayGapHandlers.delete(handler);
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
    void this.openSocket(endpoint, this.lastSequence, this.streamEpoch);
  }

  close(): void {
    this.manuallyClosed = true;
    this.clearReconnectTimer();
    this.stopHeartbeat();
    this.endpoint = "";
    this.closeSocket();
  }

  private async openSocket(
    endpoint: string,
    sinceSeq?: number,
    epoch?: string,
  ): Promise<void> {
    const generation = ++this.socketGeneration;
    const url = new URL(endpoint);
    if (sinceSeq !== undefined) url.searchParams.set("sinceSeq", String(sinceSeq));
    // 重连时带上上次连接的纪元，服务端据此识别服务重启后的 sequence 空间不连续。
    if (epoch) url.searchParams.set("epoch", epoch);
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
        if (this.handleSystemEvent(event)) return;
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

  /** 消费系统控制事件；返回 true 表示已处理、不再上抛给业务 handler。 */
  private handleSystemEvent(event: TaskEvent): boolean {
    switch (event.eventType) {
      case "system.keepalive":
        return true;
      case "system.ready": {
        const data = event.data as Record<string, unknown>;
        const nextEpoch = typeof data.streamEpoch === "string" ? data.streamEpoch : undefined;
        const epochChanged =
          nextEpoch !== undefined && this.streamEpoch !== undefined && this.streamEpoch !== nextEpoch;
        const gapFromServer = this.gapPendingThisReady;
        this.gapPendingThisReady = false;
        this.streamEpoch = nextEpoch;
        if (gapFromServer) {
          // server 已发 system.replay_gap，游标已由该事件清空，这里只消费标记。
          return true;
        }
        if (epochChanged) {
          // 兜底：服务端未显式发 replay_gap 但纪元变化（如旧版服务端），
          // 同样清空旧 cursor 并通知上层做权威刷新。
          this.lastSequence = undefined;
          this.emitReplayGap({
            reason: "epoch_changed",
            streamEpoch: nextEpoch ?? "",
            oldestSequence: toNumber(data.oldestSequence, 0),
            currentSequence: toNumber(data.currentSequence, 0),
          });
        }
        return true;
      }
      case "system.replay_gap": {
        // 游标失效：清空，避免下次重连带旧 sequence 跳回放窗口。标记待
        // 下一个 system.ready 消费，防止同一次缺口重复上报。
        this.lastSequence = undefined;
        this.gapPendingThisReady = true;
        const data = event.data as Record<string, unknown>;
        this.emitReplayGap({
          reason: (data.reason as ReplayGapInfo["reason"]) ?? "epoch_changed",
          streamEpoch: typeof data.streamEpoch === "string" ? data.streamEpoch : "",
          oldestSequence: toNumber(data.oldestSequence, 0),
          currentSequence: toNumber(data.currentSequence, 0),
          requestedSinceSeq:
            typeof data.requestedSinceSeq === "number" ? data.requestedSinceSeq : undefined,
          previousEpoch: typeof data.previousEpoch === "string" ? data.previousEpoch : undefined,
          message: typeof data.message === "string" ? data.message : undefined,
        });
        return true;
      }
      default:
        return false;
    }
  }

  private emitReplayGap(info: ReplayGapInfo): void {
    this.replayGapHandlers.forEach((handler) => handler(info));
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
    const delayMs = reconnectDelayMs(this.reconnectAttempt);
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (this.manuallyClosed || this.endpoint !== endpoint) return;
      void this.openSocket(endpoint, this.lastSequence, this.streamEpoch);
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
