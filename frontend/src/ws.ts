import type { TaskEvent } from "./types";

type EventHandler = (event: TaskEvent) => void;
type StatusHandler = (status: "connected" | "disconnected" | "error") => void;

function wsBaseUrl(): string {
  const explicit = import.meta.env.VITE_ARGUS_WS_BASE;
  if (explicit) return String(explicit).replace(/\/$/, "");
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/v1`;
}

export class TaskEventStream {
  private socket: WebSocket | null = null;
  private endpoint = "";
  private reconnectTimer: number | null = null;
  private reconnectAttempt = 0;
  private manuallyClosed = false;
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
    if (
      this.socket &&
      this.endpoint === endpoint &&
      this.socket.readyState <= WebSocket.OPEN
    ) {
      return;
    }
    this.clearReconnectTimer();
    this.manuallyClosed = false;
    this.closeSocket();
    this.endpoint = endpoint;
    this.openSocket(endpoint);
  }

  close(): void {
    this.manuallyClosed = true;
    this.clearReconnectTimer();
    this.endpoint = "";
    this.closeSocket();
  }

  private openSocket(endpoint: string): void {
    const socket = new WebSocket(endpoint);
    this.socket = socket;

    socket.addEventListener("open", () => {
      if (this.socket !== socket || this.endpoint !== endpoint) return;
      this.reconnectAttempt = 0;
      this.emitStatus("connected");
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
      try {
        const event = JSON.parse(String(message.data)) as TaskEvent;
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

  private emitStatus(status: "connected" | "disconnected" | "error"): void {
    this.statusHandlers.forEach((handler) => handler(status));
  }

  private scheduleReconnect(endpoint: string): void {
    this.clearReconnectTimer();
    const delayMs = Math.min(1000 * 2 ** this.reconnectAttempt, 15000);
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (this.manuallyClosed || this.endpoint !== endpoint) return;
      this.openSocket(endpoint);
    }, delayMs);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
