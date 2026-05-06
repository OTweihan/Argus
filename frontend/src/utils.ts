import { ApiError } from "./api";
import type { Task, TaskDisplayStatus } from "./types";

export function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
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
  const trimmed = value.trim();
  return trimmed || null;
}

export function nullableNumber(value: string, label: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const number = Number(trimmed);
  if (!Number.isFinite(number)) {
    throw new Error(`${label} 必须是有效数字。`);
  }
  return number;
}

export function parseJsonObject(value: string, label: string): Record<string, unknown> {
  const trimmed = value.trim();
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
  if (error instanceof ApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return "未知错误。";
}
