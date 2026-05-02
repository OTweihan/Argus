import type { ConfigSummary, ModelConfig, Project, Task, TaskStatus } from "./types";

export type ViewKey = "dashboard" | "projects" | "tasks" | "models";

export interface AppState {
  view: ViewKey;
  loading: boolean;
  message: string;
  error: string;
  summary: ConfigSummary | null;
  projects: Project[];
  allTasks: Task[];
  visibleTasks: Task[];
  models: ModelConfig[];
  selectedTaskId: string | null;
  taskStatusFilter: TaskStatus | "";
  taskProjectFilter: string;
  eventStatus: "connected" | "disconnected" | "error";
}

export const state: AppState = {
  view: "dashboard",
  loading: false,
  message: "",
  error: "",
  summary: null,
  projects: [],
  allTasks: [],
  visibleTasks: [],
  models: [],
  selectedTaskId: null,
  taskStatusFilter: "",
  taskProjectFilter: "",
  eventStatus: "disconnected",
};

export function patchState(updates: Partial<AppState>): AppState {
  Object.assign(state, updates);
  return state;
}
