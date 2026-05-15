import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";

import { ElMessage } from "element-plus";
import { summary as apiSummary } from "../api";
import type { ConfigSummary, ModelConfig, Project, Task } from "../types";
import { compact, errorMessage } from "../utils";
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

export function useConsoleApp() {
    const loading = ref(false);
    const message = ref("");
    const error = ref("");
    const summary = ref<ConfigSummary | null>(null);
    const formErrors = reactive<Record<string, string>>({});
    const projects = ref<Project[]>([]);
    const allTasks = ref<Task[]>([]);
    const models = ref<ModelConfig[]>([]);

    // P1-13：dashboard 相关 ref / loader / computed 抽到 useDashboardStats。
    const dashboard = useDashboardStats({ error });

    const nav = useNavigation();
    const dialog = useDialog();
    const events = useRuntimeEvents();

    const taskDomain = useTasks({
        allTasks, projects, models, error, message, formErrors,
        view: nav.view,
    });

    const projectDomain = useProjects({ projects, error, message, formErrors });

    const modelDomain = useModels({ models, error, message, formErrors, dialog: dialog.dialog });

    /* ── 事件订阅 ── */

    const taskEvents = useTaskEvents(
        allTasks,
        taskDomain.loadTasks,
        taskDomain.selectedTaskId,
        (msg) => { error.value = msg; },
        (s) => { summary.value = s; },
        dashboard.loadDashboardStats,
    );
    events.onTaskEvent((event) => taskEvents.applyEvent(event));

    /* ── 视图与 WebSocket 编排 ──
     *
     * P1-13：之前 `useTasks → useTaskSelection.selectTask` 主动回调 `connectEventStream`，
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
            return taskDomain.selectedTask.value ? compact(taskDomain.selectedTask.value.goal, 60) : "任务详情";
        }
        return {
            dashboard: "仪表盘",
            projects: "项目管理",
            tasks: "任务管理",
            models: "模型配置",
        }[nav.view.value] ?? "";
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

    watch(error, (val) => {
        if (val) {
            ElMessage({ message: val, type: "error", duration: 5000 });
        }
    });

    watch(message, (val) => {
        if (val) {
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
        loading.value = true;
        error.value = "";
        message.value = "";
        try {
            const [summaryResponse] = await Promise.all([
                apiSummary(),
                projectDomain.loadProjects(),
                taskDomain.loadTasks(),
                modelDomain.loadModels(),
                dashboard.loadDashboardStats(),
            ]);
            summary.value = summaryResponse;
        } catch (caught) {
            error.value = errorMessage(caught);
        } finally {
            loading.value = false;
        }
    }

    return {
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
        loading,
        message,
        modelForm: modelDomain.modelForm,
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
        showModelDialog: modelDomain.showModelDialog,
        showProjectDialog: projectDomain.showProjectDialog,
        showTaskDialog: taskDomain.showTaskDialog,
        startTask: taskDomain.startTask,
        retryTask: taskDomain.retryTask,
        taskForm: taskDomain.taskForm,
        taskLoading: taskDomain.taskLoading,
        taskProjectFilter: taskDomain.taskProjectFilter,
        taskSearchQuery: taskDomain.taskSearchQuery,
        taskStatuses: taskDomain.taskStatuses,
        taskStatusFilter: taskDomain.taskStatusFilter,
        testModel: modelDomain.testModel,
        total: taskDomain.total,
        view: nav.view,
        viewTitle,
    };
}
