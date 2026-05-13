import { computed, onMounted, reactive, ref, watch, type Ref } from "vue";

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

    // 占位 ref，useTasks 返回后替换为真实引用
    let selectedTaskIdRef: Ref<string | null> = ref(null);

    function connectEventStream(): void {
        events.connectEventStream(nav.view, selectedTaskIdRef);
    }

    const taskDomain = useTasks({
        allTasks, projects, models, error, message, formErrors,
        view: nav.view,
        connectEventStream,
    });
    selectedTaskIdRef = taskDomain.selectedTaskId;

    const projectDomain = useProjects({ projects, error, message, formErrors });

    const modelDomain = useModels({ models, error, message, formErrors, dialog: dialog.dialog });

    /* ── 事件订阅 ── */

    const taskEvents = useTaskEvents(
        allTasks,
        taskDomain.loadTasks,
        selectedTaskIdRef,
        (msg) => { error.value = msg; },
        (s) => { summary.value = s; },
    );
    events.onTaskEvent((event) => taskEvents.applyEvent(event));

    /* ── 视图切换（恢复旧逻辑中丢失的 side effect） ── */

    watch(nav.view, () => {
        connectEventStream();
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
