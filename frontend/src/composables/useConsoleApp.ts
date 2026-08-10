import {
  computed,
  inject,
  nextTick,
  onMounted,
  provide,
  reactive,
  ref,
  watch,
  type InjectionKey,
} from "vue";

import { ElMessage } from "element-plus";
import type { ModelConfig, Project, Task } from "../types";
import { compact, displayTaskName, errorMessage } from "../utils";
import { useDashboardStats } from "./useDashboardStats";
import { useDialog } from "./useDialog";
import { useModels } from "./useModels";
import { useNavigation } from "./useNavigation";
import { useProjects } from "./useProjects";
import { useRuntimeEvents } from "./useRuntimeEvents";
import { useTaskEvents } from "./useTaskEvents";
import { useTasks } from "./useTasks";

import type { ViewKey } from "./useNavigation";
export type { ViewKey };

export const ConsoleAppKey: InjectionKey<ReturnType<typeof useConsoleApp>> = Symbol("ConsoleApp");

export function useConsoleApp() {
  const message = ref("");
  const error = ref("");
  const formErrors = reactive<Record<string, string>>({});
  const projects = ref<Project[]>([]);
  const allTasks = ref<Task[]>([]);
  const models = ref<ModelConfig[]>([]);
  // 时间线/日志重拉信号：回放缺口时自增，TaskTimeline 监听后从 SQLite 权威重拉，
  // 补齐断线期间遗漏的持久化时间线事件。
  const timelineReloadTick = ref(0);

  // dashboard 相关 ref / loader / computed 抽到 useDashboardStats。
  const dashboard = useDashboardStats({ error });

  const nav = useNavigation();
  const dialog = useDialog();
  const events = useRuntimeEvents();

  const taskDomain = useTasks({
    allTasks,
    projects,
    models,
    error,
    message,
    formErrors,
    view: nav.view,
  });

  const projectDomain = useProjects({ projects, error, message, formErrors });

  const modelDomain = useModels({ models, error, message, formErrors, dialog: dialog.dialog });

  /* ── 事件订阅 ── */

  const taskEvents = useTaskEvents(
    allTasks,
    taskDomain.loadTasks,
    taskDomain.selectedTaskId,
    (msg) => {
      error.value = msg;
    },
    dashboard.loadDashboardStats,
  );
  events.onTaskEvent((event) => taskEvents.applyEvent(event));
  events.onReconnect(() => taskEvents.scheduleStatsRefresh());
  // 回放缺口（sinceSeq 超窗 / 服务重启 epoch 变化）：WebSocket 游标已失效，改由
  // SQLite 权威刷新可见列表、当前任务与 dashboard；时间线组件监听 reloadTick
  // 变化重拉持久化时间线。实时 patch 继续走 onTaskEvent，二者以服务端快照为准，
  // 不会相互覆盖（见 useTaskEvents 的权威刷新代次）。
  events.onReplayGap(() => {
    void taskEvents.refreshRuntimeData();
    timelineReloadTick.value += 1;
  });

  /* ── 视图与 WebSocket 编排 ──
   *
   * 之前 `useTasks → useTaskSelection.selectTask` 主动回调 `connectEventStream`，
   * 而 `connectEventStream` 闭包又需要 `taskDomain.selectedTaskId`，形成"鸡生蛋"，
   * 用 holder ref 后期填充绕过。现在反向：让 useTasks 只更新状态，编排层 watch
   * `[view, selectedTaskId]` 任一变化都触发 WS 重连，Vue 批量更新机制保证两者
   * 同 tick 变化时只触发一次。
   */
  function connectEventStream(): void {
    events.connectEventStream(nav.view, taskDomain.selectedTaskId);
  }

  watch([nav.view, taskDomain.selectedTaskId], () => {
    // nextTick 确保视图切换渲染完成后再重连 WebSocket，
    // 避免 event replay 触发 allTasks 更新导致 el-table 闪烁。
    nextTick(() => connectEventStream());
  });

  function changeView(nextView: ViewKey): void {
    nav.changeView(nextView);
    error.value = "";
    message.value = "";
    // 不再主动调 connectEventStream：watch(view) 已经接管。
  }

  /* ── 计算属性 ── */

  // 仪表盘指标已抽到 useDashboardStats（tasksTotal / runningCount /
  // findingCount / recentTasks），下面只保留 useConsoleApp 自己需要的派生项。
  const enabledModels = computed(() => models.value.filter((model) => model.enabled));

  const viewTitle = computed(() => {
    if (nav.view.value === "task-detail") {
      const task = taskDomain.selectedTask.value;
      if (!task) return "报告详情";
      // 顶部标题优先使用任务名（含重试次数），与任务列表口径一致；
      // 旧任务缺失 name 时回落到目标文案。
      const name = task.name?.trim();
      return name ? displayTaskName(task) : compact(task.goal, 60);
    }
    return (
      {
        dashboard: "仪表盘",
        projects: "项目管理",
        tasks: "任务管理",
        models: "模型配置",
      }[nav.view.value] ?? ""
    );
  });

  /* ── 监听器 ── */

  watch(
    () => projects.value,
    () => {
      if (!taskDomain.taskForm.projectId && projects.value[0]) {
        taskDomain.taskForm.projectId = projects.value[0].projectId;
      }
    },
  );

  let _lastErrorToast = 0;
  watch(error, (val) => {
    if (val) {
      const now = Date.now();
      if (now - _lastErrorToast < 2000) return;
      _lastErrorToast = now;
      ElMessage({ message: val, type: "error", duration: 5000 });
    }
  });

  let _lastMessageToast = 0;
  watch(message, (val) => {
    if (val) {
      const now = Date.now();
      if (now - _lastMessageToast < 2000) return;
      _lastMessageToast = now;
      ElMessage({ message: val, type: "success", duration: 3000 });
    }
  });

  /* ── 生命周期 ── */

  onMounted(async () => {
    await loadAll();
    connectEventStream();
    // 刷新后自动恢复任务详情视图
    if (nav.initialDetailTaskId.value && taskDomain.selectTask) {
      taskDomain.selectTask(nav.initialDetailTaskId.value);
    }
  });

  /* ── 数据加载 ── */

  async function loadAll(): Promise<void> {
    error.value = "";
    message.value = "";
    try {
      await Promise.all([
        projectDomain.loadProjects(),
        taskDomain.loadTasks(),
        modelDomain.loadModels(),
        dashboard.loadDashboardStats(),
      ]);
    } catch (caught) {
      error.value = errorMessage(caught);
    }
  }

  const result = {
    addParam: taskDomain.addParam,
    allTasks,
    dashboardStats: dashboard.dashboardStats,
    tasksTotal: dashboard.tasksTotal,
    changeView,
    closeDialog: dialog.closeDialog,
    deleteTask: taskDomain.deleteTask,
    deleteModel: modelDomain.deleteModel,
    deleteProject: projectDomain.deleteProject,
    dialog: dialog.dialog,
    dialogVisible: dialog.dialogVisible,
    editModel: modelDomain.editModel,
    editProject: projectDomain.editProject,
    enabledModels,
    error,
    eventStatus: events.eventStatus,
    eventStatusText: events.eventStatusText,
    onTaskEvent: events.onTaskEvent,
    findingCount: dashboard.findingCount,
    formErrors,
    goBackToTasks: taskDomain.goBackToTasks,
    loadAll,
    message,
    modelForm: modelDomain.modelForm,
    modelLoading: modelDomain.modelLoading,
    models,
    onPageChange: taskDomain.onPageChange,
    onPageSizeChange: taskDomain.onPageSizeChange,
    openNewModelDialog: modelDomain.openNewModelDialog,
    openNewProjectDialog: projectDomain.openNewProjectDialog,
    openEditTaskDialog: taskDomain.openEditTaskDialog,
    openNewTaskDialog: taskDomain.openNewTaskDialog,
    page: taskDomain.page,
    pageSize: taskDomain.pageSize,
    projectForm: projectDomain.projectForm,
    projectLoading: projectDomain.projectLoading,
    projects,
    recentTasks: dashboard.recentTasks,
    removeParam: taskDomain.removeParam,
    reportData: taskDomain.reportData,
    reportLoading: taskDomain.reportLoading,
    resetModelForm: modelDomain.resetModelForm,
    resetProjectForm: projectDomain.resetProjectForm,
    runningCount: dashboard.runningCount,
    saveModel: modelDomain.saveModel,
    saveProject: projectDomain.saveProject,
    saveTask: taskDomain.saveTask,
    selectTask: taskDomain.selectTask,
    selectedTaskTab: taskDomain.selectedTaskTab,
    selectedTask: taskDomain.selectedTask,
    setDefaultModel: modelDomain.setDefaultModel,
    showModelDialog: modelDomain.showModelDialog,
    showProjectDialog: projectDomain.showProjectDialog,
    showTaskDialog: taskDomain.showTaskDialog,
    startTask: taskDomain.startTask,
    retryTask: taskDomain.retryTask,
    statsLoading: dashboard.statsLoading,
    taskForm: taskDomain.taskForm,
    taskLoading: taskDomain.taskLoading,
    taskProjectFilter: taskDomain.taskProjectFilter,
    taskSearchQuery: taskDomain.taskSearchQuery,
    taskStatuses: taskDomain.taskStatuses,
    taskStatusFilter: taskDomain.taskStatusFilter,
    taskTypeFilter: taskDomain.taskTypeFilter,
    testModel: modelDomain.testModel,
    timelineReloadTick,
    total: taskDomain.total,
    view: nav.view,
    viewTitle,
  };

  provide(ConsoleAppKey, result);
  return result;
}

export function injectConsoleApp(): ReturnType<typeof useConsoleApp> {
  const app = inject(ConsoleAppKey);
  if (!app) throw new Error("injectConsoleApp() 必须在 App.vue 的后代组件中调用");
  return app;
}
