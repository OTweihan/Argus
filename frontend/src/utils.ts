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
  if (task.status === "pending" && task.schedulerStatus) return task.schedulerStatus as SchedulerStatus;
  return task.status;
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
