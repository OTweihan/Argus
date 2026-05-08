import { ApiError } from "./api";
import type { Task, TaskDisplayStatus } from "./types";

export function formatDate(value: string | null): string {
  if (!value) return "-";
  const d = new Date(value);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function compact(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length - 1)}...` : value;
}

export function taskDisplayStatus(task: Task): TaskDisplayStatus {
  if (task.status === "pending" && task.schedulerStatus) return task.schedulerStatus;
  return task.status;
}

export function canStartTask(task: Task): boolean {
  return task.status === "pending" && !task.schedulerStatus;
}

export function nullableText(value: string): string | null {
  const trimmed = String(value ?? "").trim();
  return trimmed || null;
}

export function nullableNumber(value: string, label: string): number | null {
  const trimmed = String(value ?? "").trim();
  if (!trimmed) return null;
  const number = Number(trimmed);
  if (!Number.isFinite(number)) {
    throw new Error(`${label} 必须是有效数字。`);
  }
  return number;
}

export function parseJsonObject(value: string, label: string): Record<string, unknown> {
  const trimmed = String(value ?? "").trim();
  if (!trimmed) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed) as unknown;
  } catch {
    throw new Error(`${label} 必须是合法 JSON。`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象。`);
  }
  return parsed as Record<string, unknown>;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "未知错误。";
}

export function errorCode(error: unknown): string | undefined {
  if (error instanceof ApiError) return error.code;
  return undefined;
}

export function nullableBoolean(value: "" | "true" | "false"): boolean | null {
  if (!value) return null;
  return value === "true";
}

export function upsertById<T extends Record<K, string>, K extends keyof T>(
  items: T[],
  item: T,
  key: K,
): T[] {
  const index = items.findIndex((current) => current[key] === item[key]);
  if (index < 0) return [item, ...items];
  return items.map((current, currentIndex) => (currentIndex === index ? item : current));
}

/** Injects a click handler into report HTML so anchor (#) links scroll inside the iframe
 *  while all other links open in a new tab instead of navigating the iframe. */
export function injectReportLinkHandler(html: string): string {
  const script =
    '<script>document.addEventListener("click",function(e){var a=e.target.closest("a");if(!a||!a.href)return;var h=a.getAttribute("href");if(h&&h[0]==="#")return;e.preventDefault();window.open(a.href,"_blank")})</script>';
  return html.replace("</head>", script + "</head>");
}
