import { ApiError } from "./api";
import type { SchedulerStatus, Task, TaskDisplayStatus } from "./types";

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
  if (task.status === "pending" && task.schedulerStatus)
    return task.schedulerStatus as SchedulerStatus;
  return task.status;
}

type TaskNameDisplaySource = { name?: string | null; executionAttempt?: number | null };

export function displayTaskName(task: TaskNameDisplaySource): string {
  const base = task.name?.trim() || "";
  if (!base) return "-";
  const attempt = task.executionAttempt ?? 1;
  return `${base}（第${attempt}次）`;
}

export function canStartTask(task: Task): boolean {
  return task.status === "pending" && !task.schedulerStatus;
}

export function canRestartTask(task: Task): boolean {
  return ["failed", "timeout", "cancelled"].includes(task.status);
}

export function nullableText(value: string): string | null {
  const trimmed = String(value ?? "").trim();
  return trimmed || null;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "未知错误。";
}

/** 请求是否因主动取消（AbortController.abort() / 组件卸载）而失败。
 *
 * client.request 统一把 fetch 的 AbortError 转成 code=REQUEST_ABORTED 的 ApiError；
 * 这里兼容原生 DOMException，供调用方区分「正常取消」与真实失败，避免误弹错误提示。 */
export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof ApiError && error.code === "REQUEST_ABORTED") ||
    (error instanceof DOMException && error.name === "AbortError")
  );
}

/** 过载类错误（队列满载 / 限流）返回带"稍后重试"的明确提示，而非一般失败。 */
export function overloadMessage(error: unknown): string {
  const apiError = error instanceof ApiError ? error : undefined;
  const overloaded =
    apiError !== undefined &&
    (apiError.status === 429 ||
      apiError.status === 503 ||
      apiError.code === "TASK_QUEUE_FULL" ||
      apiError.code === "RATE_LIMITED");
  return overloaded ? "系统繁忙：任务队列已满，请稍后重试。" : errorMessage(error);
}

export function nullableBoolean(value: "" | "true" | "false"): boolean | null {
  if (!value) return null;
  return value === "true";
}

/** HTTP 方法 → Element Plus tag type。GET=success, POST=primary, PUT/PATCH=warning, DELETE=danger。 */
export type HttpMethodTagType = "success" | "info" | "danger" | "warning" | "primary";

export function httpMethodTag(method: string): HttpMethodTagType {
  switch (method.toUpperCase()) {
    case "GET":
      return "success";
    case "POST":
      return "primary";
    case "PUT":
    case "PATCH":
      return "warning";
    case "DELETE":
      return "danger";
    default:
      return "info";
  }
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

export function sortBy<T>(items: T[], pick: (item: T) => number): T[] {
  return [...items].sort((a, b) => pick(a) - pick(b));
}

/** 清除 reactive 表单错误对象的所有键。 */
export function clearFormErrors(formErrors: Record<string, string>): void {
  for (const key of Object.keys(formErrors)) {
    delete formErrors[key];
  }
}

/** 下拉框"无选择"哨兵值。 */
export const SENTINEL_DEFAULT = "__default__";
