import {computed, nextTick, onMounted, onUnmounted, reactive, ref, watch} from "vue";

import {api} from "../api";
import type {ConfigSummary, ModelConfig, Project, Task,} from "../types";
import {compact, errorMessage} from "../utils";
import {TaskEventStream} from "../ws";
import {useProjects} from "./useProjects";
import {useTasks} from "./useTasks";
import {useModels} from "./useModels";

type ViewKey = "dashboard" | "projects" | "tasks" | "models" | "task-detail";
type EventStatus = "connected" | "disconnected" | "error";
type DialogTone = "success" | "error" | "info";

interface DialogState {
  title: string;
  message: string;
  tone: DialogTone;
}

export function useConsoleApp() {
  const view = ref<ViewKey>("dashboard");
  const loading = ref(false);
  const message = ref("");
  const error = ref("");
  const summary = ref<ConfigSummary | null>(null);
  const dialog = ref<DialogState | null>(null);
  const formErrors = reactive<Record<string, string>>({});

  const projects = ref<Project[]>([]);
  const allTasks = ref<Task[]>([]);
  const models = ref<ModelConfig[]>([]);

  const eventStream = new TaskEventStream();
  let refreshTimer: number | null = null;

  const {
    projectForm, showProjectDialog,
    loadProjects, saveProject, editProject, deleteProject, openNewProjectDialog, resetProjectForm,
  } = useProjects({projects, error, message, formErrors});

  const {
    taskForm, showTaskDialog, taskStatusFilter, taskProjectFilter,
    selectedTaskId, reportData, reportLoading,
    selectedTask, visibleTasks, taskStatuses,
    loadTasks, selectTask, goBackToTasks, startTask, saveTask, openNewTaskDialog, resetTaskForm,
  } = useTasks({allTasks, projects, models, error, message, formErrors, view, connectEventStream});

  const {
    modelForm, showModelDialog, providers,
    loadModels, saveModel, editModel, deleteModel, testModel, openNewModelDialog, resetModelForm,
  } = useModels({models, error, message, formErrors, dialog});

  const viewTitle = computed(() => {
    if (view.value === "task-detail") {
      return selectedTask.value ? compact(selectedTask.value.goal, 60) : "任务详情";
    }
    return {
      dashboard: "仪表盘",
      projects: "项目管理",
      tasks: "任务管理",
      models: "模型配置",
    }[view.value] ?? "";
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
  const enabledModels = computed(() => models.value.filter((model) => model.enabled));

  const eventStatus = ref<EventStatus>("disconnected");

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
      const [summaryResponse] = await Promise.all([
        api.summary(),
        loadProjects(),
        loadTasks(),
        loadModels(),
      ]);
      summary.value = summaryResponse;
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
        api.listTasks({limit: 100}),
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

  function showDialog(title: string, dialogMessage: string, tone: DialogTone): void {
    dialog.value = {title, message: dialogMessage, tone};
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
    formErrors,
    goBackToTasks,
    loadAll,
    loading,
    message,
    modelForm,
    models,
    openNewModelDialog,
    openNewProjectDialog,
    openNewTaskDialog,
    projectForm,
    projects,
    providers,
    recentTasks,
    reportData,
    reportLoading,
    resetModelForm,
    resetProjectForm,
    runningCount,
    saveModel,
    saveProject,
    saveTask,
    selectTask,
    selectedTask,
    showModelDialog,
    showProjectDialog,
    showTaskDialog,
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
