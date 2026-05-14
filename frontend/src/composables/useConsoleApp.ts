import { computed, nextTick, onMounted, reactive, ref, watch, type Ref } from "vue";

import { ElMessage } from "element-plus";
import { summary as apiSummary } from "../api";
import type { ConfigSummary, ModelConfig, Project, Task } from "../types";
import { compact, errorMessage } from "../utils";
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

    const nav = useNavigation();
    const dialog = useDialog();
    const events = useRuntimeEvents();

    /* ── connectEventStream wrapper：需要 view（来自 nav）和 selectedTaskId（来自 useTasks） ── */

    // useTasks 需要 connectEventStream 当回调，但 connectEventStream 又需要
    // taskDomain.selectedTaskId —— 鸡生蛋。
    //
    // 用普通对象做 holder：
    //   - holder 自身是 const，``current`` 字段在 taskDomain 构造完后被替换
    //     为 taskDomain.selectedTaskId（普通字段 mutation，ESLint vue/no-ref-
    //     as-operand 不会误报；shallowRef 在此处会被 vue-tsc auto-unwrap，
    //     绕不开类型层面的 ref 解包）
    //   - useRuntimeEvents.connectEventStream 的实现是"调用瞬间读 .value"，
    //     所有真实调用时机（onMounted / watch view / changeView / selectTask）
    //     都在 holder.current 替换之后发生，闭包总是读到最新 inner ref。
    const selectedTaskIdHolder: { current: Ref<string | null> } = { current: ref(null) };

    function connectEventStream(): void {
        events.connectEventStream(nav.view, selectedTaskIdHolder.current);
    }

    const taskDomain = useTasks({
        allTasks, projects, models, error, message, formErrors,
        view: nav.view,
        connectEventStream,
    });
    selectedTaskIdHolder.current = taskDomain.selectedTaskId;

    const projectDomain = useProjects({ projects, error, message, formErrors });

    const modelDomain = useModels({ models, error, message, formErrors, dialog: dialog.dialog });

    /* ── 事件订阅 ── */

    const taskEvents = useTaskEvents(
        allTasks,
        taskDomain.loadTasks,
        // 走到这一行时 taskDomain 已就绪，直接传它的 selectedTaskId，不必再
        // 透过 holder 间接引用，类型也更直接。
        taskDomain.selectedTaskId,
        (msg) => { error.value = msg; },
        (s) => { summary.value = s; },
    );
    events.onTaskEvent((event) => taskEvents.applyEvent(event));

    /* ── 视图切换（恢复旧逻辑中丢失的 side effect） ── */

    watch(nav.view, () => {
        // nextTick 确保视图切换渲染完成后再重连 WebSocket，
        // 避免 event replay 触发 allTasks 更新导致 el-table 闪烁
        nextTick(() => connectEventStream());
    });

    function changeView(nextView: ViewKey): void {
        nav.changeView(nextView);
        error.value = "";
        message.value = "";
        connectEventStream();
    }

    /* ── 计算属性 ── */

    const runningCount = computed(() => {
        return allTasks.value.filter((task) => task.status === "running").length;
    });

    const findingCount = computed(() => {
        return allTasks.value.reduce((total, task) => total + (task.findingCount ?? task.findings?.length ?? 0), 0);
    });

    const recentTasks = computed(() => {
        return [...allTasks.value]
            .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
            .slice(0, 8);
    });

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
        findingCount,
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
        recentTasks,
        removeParam: taskDomain.removeParam,
        reportData: taskDomain.reportData,
        reportLoading: taskDomain.reportLoading,
        resetModelForm: modelDomain.resetModelForm,
        resetProjectForm: projectDomain.resetProjectForm,
        runningCount,
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
