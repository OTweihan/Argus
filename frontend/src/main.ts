import "./styles.css";

import { ApiError, api, type ModelConfigPayload, type ProjectPayload, type TaskPayload } from "./api";
import { patchState, state, type ViewKey } from "./state";
import type { ModelConfig, Project, Task, TaskStatus } from "./types";
import { closeDialog, escapeHtml, eventStatusText, navButton, showDialog, viewTitle } from "./ui";
import { renderDashboard, renderModels, renderProjects, renderTasks } from "./views";
import { TaskEventStream } from "./ws";

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("App root not found.");

const eventStream = new TaskEventStream();
let refreshTimer: number | null = null;

eventStream.onStatus((eventStatus) => {
  if (state.eventStatus === eventStatus) return;
  patchState({ eventStatus });
  render();
});

eventStream.onEvent((event) => {
  const eventType = event.eventType ?? event.type ?? "";
  if (eventType.startsWith("task.")) {
    scheduleRefresh();
  }
});

void init();

async function init(): Promise<void> {
  bindEvents();
  await loadAll();
  connectEventStream();
}

function bindEvents(): void {
  app.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLButtonElement>("[data-action]");
    const viewTarget = target.closest<HTMLElement>("[data-view]");
    if (viewTarget?.dataset.view) {
      event.preventDefault();
      changeView(viewTarget.dataset.view as ViewKey);
      return;
    }
    if (!button) return;
    void handleAction(button);
  });

  app.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.target as HTMLFormElement;
    void handleSubmit(form);
  });

  app.addEventListener("change", (event) => {
    const target = event.target as HTMLElement;
    if (target.matches("[data-filter]")) {
      void loadTasksFromFilters();
    }
  });
}

async function loadAll(): Promise<void> {
  patchState({ loading: true, error: "", message: "" });
  render();
  try {
    const [summary, projects, tasks, models] = await Promise.all([
      api.summary(),
      api.listProjects(),
      api.listTasks({ limit: 100 }),
      api.listModels(true),
    ]);
    patchTaskCollections(tasks.tasks, {
      summary,
      projects: projects.projects,
      models: models.models,
      loading: false,
    });
  } catch (error) {
    patchState({ loading: false, error: errorMessage(error) });
  }
  render();
}

async function loadTasksFromFilters(): Promise<void> {
  const status = getSelectValue("task-filter-status") as TaskStatus | "";
  const projectId = getSelectValue("task-filter-project");
  patchState({
    taskStatusFilter: status,
    taskProjectFilter: projectId,
    visibleTasks: applyTaskFilters(state.allTasks, status, projectId),
    error: "",
  });
  render();
}

function patchTaskCollections(allTasks: Task[], updates: Partial<typeof state> = {}): void {
  patchState({
    ...updates,
    allTasks,
    visibleTasks: applyTaskFilters(allTasks),
  });
}

function applyTaskFilters(
  tasks: Task[],
  status: TaskStatus | "" = state.taskStatusFilter,
  projectId: string = state.taskProjectFilter,
): Task[] {
  return tasks.filter((task) => {
    if (status && task.status !== status) return false;
    if (projectId && task.projectId !== projectId) return false;
    return true;
  });
}

function scheduleRefresh(): void {
  if (refreshTimer !== null) window.clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(() => {
    refreshTimer = null;
    void refreshRuntimeData();
  }, 350);
}

async function refreshRuntimeData(): Promise<void> {
  try {
    const [tasks, summary] = await Promise.all([api.listTasks({ limit: 100 }), api.summary()]);
    let selectedTask: Task | null = null;
    if (state.selectedTaskId) {
      selectedTask = await api.getTask(state.selectedTaskId);
    }
    const nextTasks = selectedTask
      ? tasks.tasks.map((task) => (task.taskId === selectedTask?.taskId ? selectedTask : task))
      : tasks.tasks;
    patchTaskCollections(nextTasks, { summary, error: "" });
  } catch (error) {
    patchState({ error: errorMessage(error) });
  }
  render();
}

function changeView(view: ViewKey): void {
  patchState({ view, error: "", message: "" });
  connectEventStream();
  render();
}

function connectEventStream(): void {
  if (state.view === "tasks" && state.selectedTaskId) {
    eventStream.connect(state.selectedTaskId);
    return;
  }
  eventStream.connect();
}

async function handleAction(button: HTMLButtonElement): Promise<void> {
  const action = button.dataset.action ?? "";
  const id = button.dataset.id ?? "";
  try {
    if (action === "refresh") {
      await loadAll();
      return;
    }
    if (action === "select-task") {
      patchState({ selectedTaskId: id, view: "tasks" });
      const task = await api.getTask(id);
      patchTaskCollections(upsertById(state.allTasks, task, "taskId"));
      connectEventStream();
      render();
      return;
    }
    if (action === "start-task") {
      const result = await api.startTask(id);
      patchTaskCollections(upsertById(state.allTasks, result.task, "taskId"), {
        message: `任务已入队：${result.schedulerStatus}`,
        error: "",
      });
      render();
      return;
    }
    if (action === "edit-project") {
      fillProjectForm(requireProject(id));
      return;
    }
    if (action === "delete-project" && window.confirm("确认删除这个项目？")) {
      await api.deleteProject(id);
      await loadAll();
      return;
    }
    if (action === "reset-project-form") {
      resetForm("project-form");
      return;
    }
    if (action === "edit-model") {
      fillModelForm(requireModel(id));
      return;
    }
    if (action === "delete-model" && window.confirm("确认删除这个模型配置？")) {
      await api.deleteModel(id);
      await loadAll();
      return;
    }
    if (action === "reset-model-form") {
      resetForm("model-form");
      return;
    }
    if (action === "test-model") {
      await testModelFromButton(id);
      return;
    }
    if (action === "close-dialog") {
      closeDialog();
      return;
    }
  } catch (error) {
    if (action === "test-model") {
      showDialog("模型连接检查失败", errorMessage(error), "error");
      return;
    }
    patchState({ error: errorMessage(error), message: "" });
    render();
  }
}

async function handleSubmit(form: HTMLFormElement): Promise<void> {
  try {
    if (form.id === "project-form") {
      const editingId = form.dataset.editingId;
      const payload = readProjectPayload(form);
      const project = editingId
        ? await api.updateProject(editingId, payload)
        : await api.createProject(payload);
      resetForm("project-form");
      patchState({
        projects: upsertById(state.projects, project, "projectId"),
        message: editingId ? "项目已更新。" : "项目已创建。",
        error: "",
      });
      render();
      return;
    }
    if (form.id === "task-form") {
      const task = await api.createTask(readTaskPayload(form));
      patchTaskCollections(upsertById(state.allTasks, task, "taskId"), {
        selectedTaskId: task.taskId,
        message: "任务已创建。",
        error: "",
      });
      resetForm("task-form");
      connectEventStream();
      render();
      return;
    }
    if (form.id === "model-form") {
      const editingId = form.dataset.editingId;
      const payload = readModelPayload(form);
      const model = editingId ? await api.updateModel(editingId, payload) : await api.createModel(payload);
      resetForm("model-form");
      patchState({
        models: upsertById(state.models, model, "modelConfigId"),
        message: editingId ? "模型配置已更新。" : "模型配置已创建。",
        error: "",
      });
      render();
    }
  } catch (error) {
    patchState({ error: errorMessage(error), message: "" });
    render();
  }
}

function render(): void {
  app.innerHTML = `
    <div class="shell">
      <aside class="sidebar">
        <h1 class="brand">Argus</h1>
        <nav class="nav">
          ${navButton(state.view, "dashboard", "仪表盘")}
          ${navButton(state.view, "projects", "项目")}
          ${navButton(state.view, "tasks", "任务")}
          ${navButton(state.view, "models", "模型")}
        </nav>
      </aside>
      <main class="main">
        <div class="topbar">
          <h1>${viewTitle(state.view)}</h1>
          <div class="status">
            <span class="dot ${state.eventStatus}"></span>
            <span>事件流：${eventStatusText(state.eventStatus)}</span>
            <button data-action="refresh">刷新</button>
          </div>
        </div>
        ${state.loading ? `<div class="banner">正在加载数据。</div>` : ""}
        ${state.message ? `<div class="banner">${escapeHtml(state.message)}</div>` : ""}
        ${state.error ? `<div class="banner error">${escapeHtml(state.error)}</div>` : ""}
        ${renderView()}
      </main>
    </div>
  `;
}

function renderView(): string {
  if (state.view === "projects") return renderProjects();
  if (state.view === "tasks") return renderTasks();
  if (state.view === "models") return renderModels();
  return renderDashboard();
}

function readProjectPayload(form: HTMLFormElement): ProjectPayload {
  return {
    name: text(form, "name"),
    description: nullableText(form, "description"),
    baseUrl: nullableText(form, "baseUrl"),
    gitUrl: nullableText(form, "gitUrl"),
    authStateName: nullableText(form, "authStateName"),
    defaultMaxSteps: nullableNumber(form, "defaultMaxSteps"),
    defaultTimeoutSeconds: nullableNumber(form, "defaultTimeoutSeconds"),
    defaultCaptureScreenshots: checked(form, "defaultCaptureScreenshots"),
    parameters: jsonObject(form, "parameters"),
  };
}

function readTaskPayload(form: HTMLFormElement): TaskPayload {
  return {
    goal: text(form, "goal"),
    projectId: text(form, "projectId"),
    startUrl: nullableText(form, "startUrl"),
    taskType: "blackbox",
    maxSteps: nullableNumber(form, "maxSteps"),
    timeoutSeconds: nullableNumber(form, "timeoutSeconds"),
    captureScreenshots: checked(form, "captureScreenshots"),
    modelConfigId: nullableText(form, "modelConfigId"),
    parameters: jsonObject(form, "parameters"),
  };
}

function readModelPayload(form: HTMLFormElement): ModelConfigPayload {
  const apiKey = nullableText(form, "apiKey");
  const payload: ModelConfigPayload = {
    name: text(form, "name"),
    provider: text(form, "provider") as ModelConfigPayload["provider"],
    model: text(form, "model"),
    baseUrl: nullableText(form, "baseUrl"),
    completionsPath: nullableText(form, "completionsPath"),
    maxTokens: nullableNumber(form, "maxTokens"),
    temperature: nullableNumber(form, "temperature"),
    maxRetries: nullableNumber(form, "maxRetries"),
    timeoutSeconds: nullableNumber(form, "timeoutSeconds"),
    taskType: nullableText(form, "taskType") as ModelConfigPayload["taskType"],
    isDefault: checked(form, "isDefault"),
    enabled: checked(form, "enabled"),
  };
  if (apiKey !== null) payload.apiKey = apiKey;
  return payload;
}

async function testModelFromButton(modelConfigId: string): Promise<void> {
  const form = document.querySelector<HTMLFormElement>("#model-form");
  if (!modelConfigId && !form) {
    showDialog("模型连接检查失败", "模型配置表单不存在。", "error");
    return;
  }
  if (!modelConfigId && form && !text(form, "model")) {
    showDialog("模型连接检查失败", "请先填写模型名称。", "error");
    return;
  }
  const payload = modelConfigId ? { modelConfigId } : form ? readModelPayload(form) : {};
  showDialog("模型连接检查", "正在测试模型连接...", "info");
  const result = await api.testModel(payload);
  const detail = [
    result.message,
    result.model ? `模型：${result.model}` : "",
    result.latencyMs !== null ? `耗时：${result.latencyMs}ms` : "",
  ]
    .filter(Boolean)
    .join("\n");
  showDialog("模型连接检查通过", detail, "success");
}

function fillProjectForm(project: Project): void {
  const form = requireForm("project-form");
  form.dataset.editingId = project.projectId;
  setValue(form, "name", project.name);
  setValue(form, "description", project.description ?? "");
  setValue(form, "baseUrl", project.baseUrl ?? "");
  setValue(form, "gitUrl", project.gitUrl ?? "");
  setValue(form, "authStateName", project.authStateName ?? "");
  setValue(form, "defaultMaxSteps", project.defaultMaxSteps?.toString() ?? "");
  setValue(form, "defaultTimeoutSeconds", project.defaultTimeoutSeconds?.toString() ?? "");
  setChecked(form, "defaultCaptureScreenshots", project.defaultCaptureScreenshots);
  setValue(form, "parameters", JSON.stringify(project.parameters, null, 2));
}

function fillModelForm(model: ModelConfig): void {
  const form = requireForm("model-form");
  form.dataset.editingId = model.modelConfigId;
  setValue(form, "name", model.name);
  setValue(form, "provider", model.provider);
  setValue(form, "model", model.model);
  setValue(form, "apiKey", "");
  setValue(form, "baseUrl", model.baseUrl);
  setValue(form, "completionsPath", model.completionsPath);
  setValue(form, "maxTokens", String(model.maxTokens));
  setValue(form, "temperature", String(model.temperature));
  setValue(form, "maxRetries", String(model.maxRetries));
  setValue(form, "timeoutSeconds", String(model.timeoutSeconds));
  setValue(form, "taskType", model.taskType ?? "");
  setChecked(form, "isDefault", model.isDefault);
  setChecked(form, "enabled", model.enabled);
}

function resetForm(formId: string): void {
  const form = requireForm(formId);
  form.reset();
  delete form.dataset.editingId;
  if (formId === "project-form") setValue(form, "parameters", "{}");
  if (formId === "task-form") setValue(form, "parameters", "{}");
}

function requireProject(projectId: string): Project {
  const project = state.projects.find((item) => item.projectId === projectId);
  if (!project) throw new Error("项目不存在。");
  return project;
}

function requireModel(modelConfigId: string): ModelConfig {
  const model = state.models.find((item) => item.modelConfigId === modelConfigId);
  if (!model) throw new Error("模型配置不存在。");
  return model;
}

function upsertById<T extends Record<K, string>, K extends keyof T>(items: T[], item: T, key: K): T[] {
  const index = items.findIndex((current) => current[key] === item[key]);
  if (index < 0) return [item, ...items];
  return items.map((current, currentIndex) => (currentIndex === index ? item : current));
}

function getSelectValue(id: string): string {
  return document.querySelector<HTMLSelectElement>(`#${id}`)?.value ?? "";
}

function text(form: HTMLFormElement, name: string): string {
  const field = form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null;
  return field?.value.trim() ?? "";
}

function nullableText(form: HTMLFormElement, name: string): string | null {
  const value = text(form, name);
  return value || null;
}

function nullableNumber(form: HTMLFormElement, name: string): number | null {
  const value = text(form, name);
  return value ? Number(value) : null;
}

function checked(form: HTMLFormElement, name: string): boolean {
  const field = form.elements.namedItem(name) as HTMLInputElement | null;
  return Boolean(field?.checked);
}

function jsonObject(form: HTMLFormElement, name: string): Record<string, unknown> {
  const value = text(form, name);
  if (!value) return {};
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("参数 JSON 必须是对象。");
  }
  return parsed as Record<string, unknown>;
}

function setValue(form: HTMLFormElement, name: string, value: string | null): void {
  const field = form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null;
  if (field) field.value = value ?? "";
}

function setChecked(form: HTMLFormElement, name: string, value: boolean): void {
  const field = form.elements.namedItem(name) as HTMLInputElement | null;
  if (field) field.checked = value;
}

function requireForm(formId: string): HTMLFormElement {
  const form = document.querySelector<HTMLFormElement>(`#${formId}`);
  if (!form) throw new Error("表单不存在。");
  return form;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return "未知错误。";
}
