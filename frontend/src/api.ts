import type {
  ApiErrorBody,
  ConfigSummary,
  ModelConfig,
  ModelConfigListResponse,
  ModelConnectionTestResponse,
  ModelProvider,
  Project,
  ProjectListResponse,
  Task,
  TaskListResponse,
  TaskStartResponse,
  TaskStatus,
  TaskType,
} from "./types";

const API_BASE = (import.meta.env.VITE_ARGUS_API_BASE ?? "/api/v1").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code = "HTTP_ERROR",
    public readonly details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  const body = contentType.includes("application/json")
    ? ((await response.json()) as T | ApiErrorBody)
    : ((await response.text()) as T);

  if (!response.ok) {
    const error = typeof body === "object" && body !== null ? (body as ApiErrorBody).error : undefined;
    throw new ApiError(
      error?.message ?? `请求失败：HTTP ${response.status}`,
      response.status,
      error?.code,
      error?.details,
    );
  }

  return body as T;
}

export interface ProjectPayload {
  name: string;
  description?: string | null;
  baseUrl?: string | null;
  gitUrl?: string | null;
  authStateName?: string | null;
  defaultMaxSteps?: number | null;
  defaultTimeoutSeconds?: number | null;
  defaultCaptureScreenshots?: boolean;
  parameters?: Record<string, unknown>;
}

export interface TaskPayload {
  goal: string;
  projectId: string;
  startUrl?: string | null;
  taskType?: TaskType;
  maxSteps?: number | null;
  timeoutSeconds?: number | null;
  captureScreenshots?: boolean | null;
  modelConfigId?: string | null;
  parameters?: Record<string, unknown>;
}

export interface ModelConfigPayload {
  name: string;
  provider: ModelProvider;
  model: string;
  apiKey?: string;
  baseUrl?: string | null;
  completionsPath?: string | null;
  maxTokens?: number | null;
  temperature?: number | null;
  maxRetries?: number | null;
  timeoutSeconds?: number | null;
  taskType?: TaskType | null;
  isDefault?: boolean;
  enabled?: boolean;
}

export interface ModelConnectionPayload extends Partial<ModelConfigPayload> {
  modelConfigId?: string | null;
}

export const api = {
  summary: () => request<ConfigSummary>("/config/summary"),

  listProjects: () => request<ProjectListResponse>("/projects"),
  createProject: (payload: ProjectPayload) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (projectId: string, payload: Partial<ProjectPayload>) =>
    request<Project>(`/projects/${encodeURIComponent(projectId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteProject: (projectId: string) =>
    request<void>(`/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" }),

  listTasks: (filters: { status?: TaskStatus | ""; projectId?: string; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.projectId) params.set("projectId", filters.projectId);
    if (filters.limit) params.set("limit", String(filters.limit));
    const query = params.toString();
    return request<TaskListResponse>(`/tasks${query ? `?${query}` : ""}`);
  },
  getTask: (taskId: string) => request<Task>(`/tasks/${encodeURIComponent(taskId)}`),
  createTask: (payload: TaskPayload) =>
    request<Task>("/tasks", { method: "POST", body: JSON.stringify(payload) }),
  startTask: (taskId: string) =>
    request<TaskStartResponse>(`/tasks/${encodeURIComponent(taskId)}/start`, { method: "POST" }),

  listModels: (includeDisabled = true) =>
    request<ModelConfigListResponse>(`/config/models?includeDisabled=${includeDisabled}`),
  createModel: (payload: ModelConfigPayload) =>
    request<ModelConfig>("/config/models", { method: "POST", body: JSON.stringify(payload) }),
  updateModel: (modelConfigId: string, payload: Partial<ModelConfigPayload>) =>
    request<ModelConfig>(`/config/models/${encodeURIComponent(modelConfigId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteModel: (modelConfigId: string) =>
    request<void>(`/config/models/${encodeURIComponent(modelConfigId)}`, { method: "DELETE" }),
  testModel: (payload: ModelConnectionPayload) =>
    request<ModelConnectionTestResponse>("/config/models/test", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export function reportUrl(taskId: string, json = false): string {
  return `${API_BASE}/tasks/${encodeURIComponent(taskId)}/${json ? "report.json" : "report"}`;
}
