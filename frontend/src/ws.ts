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
    this.close();
    this.endpoint = endpoint;
    this.socket = new WebSocket(endpoint);

    this.socket.addEventListener("open", () => this.emitStatus("connected"));
    this.socket.addEventListener("close", () => this.emitStatus("disconnected"));
    this.socket.addEventListener("error", () => this.emitStatus("error"));
    this.socket.addEventListener("message", (message) => {
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

  close(): void {
    if (this.socket && this.socket.readyState < WebSocket.CLOSING) {
      this.socket.close();
    }
    this.socket = null;
    this.endpoint = "";
  }

  private emitStatus(status: "connected" | "disconnected" | "error"): void {
    this.statusHandlers.forEach((handler) => handler(status));
  }
}
