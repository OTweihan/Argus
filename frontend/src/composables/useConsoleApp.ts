import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from "vue";

import {
  api,
  type ModelConfigPayload,
  type ModelConnectionPayload,
  type ProjectPayload,
} from "../api";
import type {
  ConfigSummary,
  ModelConfig,
  ModelProvider,
  Project,
  Task,
  TaskDisplayStatus,
  TaskStatus,
  TaskType,
} from "../types";
import {
  errorMessage,
  nullableNumber,
  nullableText,
  parseJsonObject,
  taskDisplayStatus,
} from "../utils";
import { TaskEventStream } from "../ws";

type ViewKey = "dashboard" | "projects" | "tasks" | "models";
type EventStatus = "connected" | "disconnected" | "error";
type DialogTone = "success" | "error" | "info";

interface DialogState {
  title: string;
  message: string;
  tone: DialogTone;
}

interface ProjectForm {
  editingId: string | null;
  name: string;
  description: string;
  baseUrl: string;
  gitUrl: string;
  authStateName: string;
  defaultMaxSteps: string;
  defaultTimeoutSeconds: string;
  defaultCaptureScreenshots: boolean;
  parameters: string;
}

interface TaskForm {
  goal: string;
  projectId: string;
  startUrl: string;
  maxSteps: string;
  timeoutSeconds: string;
  captureScreenshots: "" | "true" | "false";
  modelConfigId: string;
  parameters: string;
}

interface ModelForm {
  editingId: string | null;
  name: string;
  provider: ModelProvider;
  model: string;
  apiKey: string;
  baseUrl: string;
  completionsPath: string;
  maxTokens: string;
  temperature: string;
  maxRetries: string;
  timeoutSeconds: string;
  taskType: "" | TaskType;
  isDefault: boolean;
  enabled: boolean;
}

export function useConsoleApp() {
  const view = ref<ViewKey>("dashboard");
  const loading = ref(false);
  const message = ref("");
  const error = ref("");
  const summary = ref<ConfigSummary | null>(null);
  const projects = ref<Project[]>([]);
  const allTasks = ref<Task[]>([]);
  const models = ref<ModelConfig[]>([]);
  const selectedTaskId = ref<string | null>(null);
  const taskStatusFilter = ref<TaskDisplayStatus | "">("");
  const taskProjectFilter = ref("");
  const eventStatus = ref<EventStatus>("disconnected");
  const dialog = ref<DialogState | null>(null);

  const eventStream = new TaskEventStream();
  let refreshTimer: number | null = null;

  const taskStatuses: TaskDisplayStatus[] = [
    "pending",
    "queued",
    "running",
    "completed",
    "failed",
    "timeout",
    "cancelled",
  ];
  const providers: ModelProvider[] = ["dashscope", "openai", "ollama", "custom"];

  const projectForm = reactive<ProjectForm>(defaultProjectForm());
  const taskForm = reactive<TaskForm>(defaultTaskForm());
  const modelForm = reactive<ModelForm>(defaultModelForm());

  const viewTitle = computed(() => {
    return {
      dashboard: "仪表盘",
      projects: "项目管理",
      tasks: "任务管理",
      models: "模型配置",
    }[view.value];
  });
  const eventStatusText = computed(() => {
    return eventStatus.value === "connected"
      ? "已连接"
      : eventStatus.value === "error"
        ? "异常"
        : "未连接";
  });
  const runningCount = computed(() => {
    return allTasks.value.filter((task) => task.status === "running").length;
  });
  const findingCount = computed(() => {
    return allTasks.value.reduce((total, task) => total + task.findings.length, 0);
  });
  const recentTasks = computed(() => {
    return [...allTasks.value]
      .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
      .slice(0, 8);
  });
  const visibleTasks = computed(() => {
    return allTasks.value.filter((task) => {
      if (taskStatusFilter.value && taskDisplayStatus(task) !== taskStatusFilter.value) return false;
      if (taskProjectFilter.value && task.projectId !== taskProjectFilter.value) return false;
      return true;
    });
  });
  const selectedTask = computed(() => {
    return (
      allTasks.value.find((task) => task.taskId === selectedTaskId.value) ??
      visibleTasks.value[0] ??
      null
    );
  });
  const enabledModels = computed(() => models.value.filter((model) => model.enabled));

  eventStream.onStatus((nextStatus) => {
    eventStatus.value = nextStatus;
  });
  eventStream.onEvent((event) => {
    const eventType = event.eventType ?? event.type ?? "";
    if (eventType.startsWith("task.")) {
      scheduleRefresh();
    }
  });

  watch(
    () => projects.value,
    () => {
      if (!taskForm.projectId && projects.value[0]) {
        taskForm.projectId = projects.value[0].projectId;
      }
    },
  );

  onMounted(async () => {
    await loadAll();
    connectEventStream();
  });

  onUnmounted(() => {
    if (refreshTimer !== null) window.clearTimeout(refreshTimer);
    eventStream.close();
  });

  async function loadAll(): Promise<void> {
    loading.value = true;
    error.value = "";
    message.value = "";
    try {
      const [summaryResponse, projectResponse, taskResponse, modelResponse] = await Promise.all([
        api.summary(),
        api.listProjects(),
        api.listTasks({ limit: 100 }),
        api.listModels(true),
      ]);
      summary.value = summaryResponse;
      projects.value = projectResponse.projects;
      allTasks.value = taskResponse.tasks;
      models.value = modelResponse.models;
      if (!taskForm.projectId && projectResponse.projects[0]) {
        taskForm.projectId = projectResponse.projects[0].projectId;
      }
    } catch (caught) {
      error.value = errorMessage(caught);
    } finally {
      loading.value = false;
    }
  }

  function changeView(nextView: ViewKey): void {
    view.value = nextView;
    error.value = "";
    message.value = "";
    connectEventStream();
  }

  function connectEventStream(): void {
    if (view.value === "tasks" && selectedTaskId.value) {
      eventStream.connect(selectedTaskId.value);
      return;
    }
    eventStream.connect();
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
      const [tasks, summaryResponse] = await Promise.all([
        api.listTasks({ limit: 100 }),
        api.summary(),
      ]);
      let selectedTaskSnapshot: Task | null = null;
      if (selectedTaskId.value) {
        selectedTaskSnapshot = await api.getTask(selectedTaskId.value);
      }
      allTasks.value = selectedTaskSnapshot
        ? tasks.tasks.map((task) =>
            task.taskId === selectedTaskSnapshot?.taskId ? selectedTaskSnapshot : task,
          )
        : tasks.tasks;
      summary.value = summaryResponse;
      error.value = "";
    } catch (caught) {
      error.value = errorMessage(caught);
    }
  }

  async function selectTask(taskId: string): Promise<void> {
    try {
      selectedTaskId.value = taskId;
      view.value = "tasks";
      const task = await api.getTask(taskId);
      allTasks.value = upsertById(allTasks.value, task, "taskId");
      connectEventStream();
    } catch (caught) {
      error.value = errorMessage(caught);
    }
  }

  async function startTask(taskId: string): Promise<void> {
    try {
      const result = await api.startTask(taskId);
      allTasks.value = upsertById(allTasks.value, result.task, "taskId");
      message.value = `任务已入队：${result.schedulerStatus}`;
      error.value = "";
    } catch (caught) {
      error.value = errorMessage(caught);
      message.value = "";
    }
  }

  async function saveProject(): Promise<void> {
    try {
      const payload: ProjectPayload = {
        name: projectForm.name.trim(),
        description: nullableText(projectForm.description),
        baseUrl: nullableText(projectForm.baseUrl),
        gitUrl: nullableText(projectForm.gitUrl),
        authStateName: nullableText(projectForm.authStateName),
        defaultMaxSteps: nullableNumber(projectForm.defaultMaxSteps, "默认最大步骤"),
        defaultTimeoutSeconds: nullableNumber(projectForm.defaultTimeoutSeconds, "默认超时秒数"),
        defaultCaptureScreenshots: projectForm.defaultCaptureScreenshots,
        parameters: parseJsonObject(projectForm.parameters, "参数 JSON"),
      };
      const project = projectForm.editingId
        ? await api.updateProject(projectForm.editingId, payload)
        : await api.createProject(payload);
      const wasEditing = Boolean(projectForm.editingId);
      projects.value = upsertById(projects.value, project, "projectId");
      resetProjectForm();
      message.value = wasEditing ? "项目已更新。" : "项目已创建。";
      error.value = "";
    } catch (caught) {
      error.value = errorMessage(caught);
      message.value = "";
    }
  }

  function editProject(project: Project): void {
    Object.assign(projectForm, {
      editingId: project.projectId,
      name: project.name,
      description: project.description ?? "",
      baseUrl: project.baseUrl ?? "",
      gitUrl: project.gitUrl ?? "",
      authStateName: project.authStateName ?? "",
      defaultMaxSteps: project.defaultMaxSteps?.toString() ?? "",
      defaultTimeoutSeconds: project.defaultTimeoutSeconds?.toString() ?? "",
      defaultCaptureScreenshots: project.defaultCaptureScreenshots,
      parameters: JSON.stringify(project.parameters, null, 2),
    });
  }

  async function deleteProject(projectId: string): Promise<void> {
    if (!window.confirm("确认删除这个项目？")) return;
    try {
      await api.deleteProject(projectId);
      await loadAll();
    } catch (caught) {
      error.value = errorMessage(caught);
    }
  }

  function resetProjectForm(): void {
    Object.assign(projectForm, defaultProjectForm());
  }

  async function saveTask(): Promise<void> {
    try {
      const task = await api.createTask({
        goal: taskForm.goal.trim(),
        projectId: taskForm.projectId,
        startUrl: nullableText(taskForm.startUrl),
        taskType: "blackbox",
        maxSteps: nullableNumber(taskForm.maxSteps, "最大步骤"),
        timeoutSeconds: nullableNumber(taskForm.timeoutSeconds, "超时秒数"),
        captureScreenshots: nullableBoolean(taskForm.captureScreenshots),
        modelConfigId: nullableText(taskForm.modelConfigId),
        parameters: parseJsonObject(taskForm.parameters, "参数 JSON"),
      });
      allTasks.value = upsertById(allTasks.value, task, "taskId");
      selectedTaskId.value = task.taskId;
      resetTaskForm();
      connectEventStream();
      message.value = "任务已创建。";
      error.value = "";
    } catch (caught) {
      error.value = errorMessage(caught);
      message.value = "";
    }
  }

  function resetTaskForm(): void {
    Object.assign(taskForm, defaultTaskForm(projects.value[0]?.projectId ?? ""));
  }

  async function saveModel(): Promise<void> {
    try {
      const payload = readModelPayload();
      const model = modelForm.editingId
        ? await api.updateModel(modelForm.editingId, payload)
        : await api.createModel(payload);
      models.value = upsertById(models.value, model, "modelConfigId");
      const wasEditing = Boolean(modelForm.editingId);
      resetModelForm();
      message.value = wasEditing ? "模型配置已更新。" : "模型配置已创建。";
      error.value = "";
    } catch (caught) {
      error.value = errorMessage(caught);
      message.value = "";
    }
  }

  function editModel(model: ModelConfig): void {
    Object.assign(modelForm, {
      editingId: model.modelConfigId,
      name: model.name,
      provider: model.provider,
      model: model.model,
      apiKey: "",
      baseUrl: model.baseUrl,
      completionsPath: model.completionsPath,
      maxTokens: String(model.maxTokens),
      temperature: String(model.temperature),
      maxRetries: String(model.maxRetries),
      timeoutSeconds: String(model.timeoutSeconds),
      taskType: model.taskType ?? "",
      isDefault: model.isDefault,
      enabled: model.enabled,
    });
  }

  async function deleteModel(modelConfigId: string): Promise<void> {
    if (!window.confirm("确认删除这个模型配置？")) return;
    try {
      await api.deleteModel(modelConfigId);
      await loadAll();
    } catch (caught) {
      error.value = errorMessage(caught);
    }
  }

  async function testModel(modelConfigId: string): Promise<void> {
    try {
      if (!modelConfigId && !modelForm.model.trim()) {
        showDialog("模型连接检查失败", "请先填写模型名称。", "error");
        return;
      }
      const payload: ModelConnectionPayload = modelConfigId ? { modelConfigId } : readModelPayload();
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
    } catch (caught) {
      showDialog("模型连接检查失败", errorMessage(caught), "error");
    }
  }

  function resetModelForm(): void {
    Object.assign(modelForm, defaultModelForm());
  }

  function readModelPayload(): ModelConfigPayload {
    const apiKey = nullableText(modelForm.apiKey);
    const payload: ModelConfigPayload = {
      name: modelForm.name.trim(),
      provider: modelForm.provider,
      model: modelForm.model.trim(),
      baseUrl: nullableText(modelForm.baseUrl),
      completionsPath: nullableText(modelForm.completionsPath),
      maxTokens: nullableNumber(modelForm.maxTokens, "最大 Token"),
      temperature: nullableNumber(modelForm.temperature, "温度"),
      maxRetries: nullableNumber(modelForm.maxRetries, "重试次数"),
      timeoutSeconds: nullableNumber(modelForm.timeoutSeconds, "超时秒数"),
      taskType: modelForm.taskType || null,
      isDefault: modelForm.isDefault,
      enabled: modelForm.enabled,
    };
    if (apiKey !== null) payload.apiKey = apiKey;
    return payload;
  }

  function showDialog(title: string, dialogMessage: string, tone: DialogTone): void {
    dialog.value = { title, message: dialogMessage, tone };
    void nextTick(() => {
      document.querySelector<HTMLButtonElement>(".dialog-actions button")?.focus();
    });
  }

  function closeDialog(): void {
    dialog.value = null;
  }

  return {
    allTasks,
    changeView,
    closeDialog,
    deleteModel,
    deleteProject,
    dialog,
    editModel,
    editProject,
    enabledModels,
    error,
    eventStatus,
    eventStatusText,
    findingCount,
    loadAll,
    loading,
    message,
    modelForm,
    models,
    projectForm,
    projects,
    providers,
    recentTasks,
    resetModelForm,
    resetProjectForm,
    runningCount,
    saveModel,
    saveProject,
    saveTask,
    selectTask,
    selectedTask,
    startTask,
    taskForm,
    taskProjectFilter,
    taskStatuses,
    taskStatusFilter,
    testModel,
    view,
    viewTitle,
    visibleTasks,
  };
}

function nullableBoolean(value: "" | "true" | "false"): boolean | null {
  if (!value) return null;
  return value === "true";
}

function upsertById<T extends Record<K, string>, K extends keyof T>(
  items: T[],
  item: T,
  key: K,
): T[] {
  const index = items.findIndex((current) => current[key] === item[key]);
  if (index < 0) return [item, ...items];
  return items.map((current, currentIndex) => (currentIndex === index ? item : current));
}

function defaultProjectForm(): ProjectForm {
  return {
    editingId: null,
    name: "",
    description: "",
    baseUrl: "",
    gitUrl: "",
    authStateName: "",
    defaultMaxSteps: "",
    defaultTimeoutSeconds: "",
    defaultCaptureScreenshots: true,
    parameters: "{}",
  };
}

function defaultTaskForm(projectId = ""): TaskForm {
  return {
    goal: "",
    projectId,
    startUrl: "",
    maxSteps: "",
    timeoutSeconds: "",
    captureScreenshots: "",
    modelConfigId: "",
    parameters: "{}",
  };
}

function defaultModelForm(): ModelForm {
  return {
    editingId: null,
    name: "",
    provider: "dashscope",
    model: "",
    apiKey: "",
    baseUrl: "",
    completionsPath: "/chat/completions",
    maxTokens: "4096",
    temperature: "0.1",
    maxRetries: "3",
    timeoutSeconds: "60",
    taskType: "",
    isDefault: false,
    enabled: true,
  };
}
