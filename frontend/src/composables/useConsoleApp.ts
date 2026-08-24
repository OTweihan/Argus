import {
  computed,
  inject,
  onMounted,
  provide,
  reactive,
  ref,
  watch,
  type InjectionKey,
} from "vue";

import type { ModelConfig, Project, Task } from "../types";
import { errorMessage } from "../utils";
import { useDashboardStats } from "./useDashboardStats";
import { useDialog } from "./useDialog";
import { useModels } from "./useModels";
import { useNavigation } from "./useNavigation";
import { useProjects } from "./useProjects";
import { useRuntimeEvents } from "./useRuntimeEvents";
import { useTaskEvents } from "./useTaskEvents";
import { useTasks } from "./useTasks";
import { useTopBar } from "./useTopBar";

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
   * WS 重连编排已内聚到 useRuntimeEvents.watchEventStream：
   * watch `[view, selectedTaskId]` 任一变化都触发重连，Vue 批量更新机制保证
   * 两者同 tick 变化时只触发一次。
   */
  events.watchEventStream(nav.view, taskDomain.selectedTaskId);

  function changeView(nextView: ViewKey): void {
    nav.changeView(nextView);
    error.value = "";
    message.value = "";
    // 不再主动调 connectEventStream：watchEventStream 已经接管。
  }

  /* ── 计算属性 ── */

  // 仪表盘指标已抽到 useDashboardStats（tasksTotal / runningCount /
  // findingCount / recentTasks），下面只保留 useConsoleApp 自己需要的派生项。
  const enabledModels = computed(() => models.value.filter((model) => model.enabled));

  // 顶栏标题与全局节流 toast 抽到 useTopBar（F3-2）。
  const topBar = useTopBar({
    view: nav.view,
    selectedTask: taskDomain.selectedTask,
    error,
    message,
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

  /* ── 生命周期 ── */

  onMounted(async () => {
    await loadAll();
    events.connectEventStream(nav.view, taskDomain.selectedTaskId);
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
    allTasks,
    applyInferInputs: taskDomain.applyInferInputs,
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
    viewTitle: topBar.viewTitle,
  };

  provide(ConsoleAppKey, result);
  return result;
}

export function injectConsoleApp(): ReturnType<typeof useConsoleApp> {
  const app = inject(ConsoleAppKey);
  if (!app) throw new Error("injectConsoleApp() 必须在 App.vue 的后代组件中调用");
  return app;
}
