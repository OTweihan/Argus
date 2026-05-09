import {computed, nextTick, onMounted, onUnmounted, reactive, ref, watch} from "vue";

import {ElMessage} from "element-plus";
import {getTask as apiGetTask, summary as apiSummary} from "../api";
import type {ConfigSummary, ModelConfig, Project, Task, TaskEvent} from "../types";
import {compact, errorMessage, upsertById} from "../utils";
import {TaskEventStream} from "../ws";
import {useProjects} from "./useProjects";
import {useTasks} from "./useTasks";
import {useModels} from "./useModels";

export type ViewKey = "dashboard" | "projects" | "tasks" | "models" | "task-detail";
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
        taskSearchQuery, selectedTaskId, reportData, reportLoading,
        selectedTask, page, pageSize, total, taskLoading, taskStatuses,
        loadTasks, onPageChange, onPageSizeChange,
        selectTask, goBackToTasks, startTask, deleteTask, saveTask, openNewTaskDialog, openEditTaskDialog, resetTaskForm,
        addParam, removeParam,
    } = useTasks({allTasks, projects, models, error, message, formErrors, view, connectEventStream});

    const {
        modelForm, showModelDialog,
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
        return allTasks.value.reduce((total, task) => total + (task.findingCount ?? task.findings?.length ?? 0), 0);
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
        if (!eventType.startsWith("task.")) return;
        applyEvent(event);
    });

    watch(
        () => projects.value,
        () => {
            if (!taskForm.projectId && projects.value[0]) {
                taskForm.projectId = projects.value[0].projectId;
            }
        },
    );

    watch(error, (val) => {
        if (val) {
            ElMessage({message: val, type: "error", duration: 5000});
        }
    });

    watch(message, (val) => {
        if (val) {
            ElMessage({message: val, type: "success", duration: 3000});
        }
    });

    onMounted(async () => {
        const hash = window.location.hash.replace(/^#/, "");
        if ((["dashboard", "projects", "tasks", "models", "task-detail"] as ViewKey[]).includes(hash as ViewKey)) {
            view.value = hash as ViewKey;
        }
        window.addEventListener("hashchange", onHashChange);
        await loadAll();
        connectEventStream();
    });

    onUnmounted(() => {
        if (refreshTimer !== null) window.clearTimeout(refreshTimer);
        window.removeEventListener("hashchange", onHashChange);
        eventStream.close();
    });

    async function loadAll(): Promise<void> {
        loading.value = true;
        error.value = "";
        message.value = "";
        try {
            const [summaryResponse] = await Promise.all([
                apiSummary(),
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
        window.location.hash = nextView;
        error.value = "";
        message.value = "";
        connectEventStream();
    }

    function onHashChange(): void {
        const hash = window.location.hash.replace(/^#/, "");
        if ((["dashboard", "projects", "tasks", "models", "task-detail"] as ViewKey[]).includes(hash as ViewKey)) {
            view.value = hash as ViewKey;
            connectEventStream();
        }
    }

    function applyEvent(event: TaskEvent): void {
        const data = event.data ?? {};
        const summary = data.task as Record<string, unknown> | undefined;
        const taskId = (summary?.taskId as string | undefined) ?? (data.taskId as string | undefined);
        if (!taskId) {
            scheduleRefresh();
            return;
        }

        const eventType = event.eventType ?? event.type ?? "";
        if (eventType === "task.deleted") {
            const idx = allTasks.value.findIndex((t) => t.taskId === taskId);
            if (idx !== -1) {
                allTasks.value = [...allTasks.value.slice(0, idx), ...allTasks.value.slice(idx + 1)];
            }
            return;
        }

        const idx = allTasks.value.findIndex((t) => t.taskId === taskId);
        if (idx === -1 && eventType === "task.created" && summary) {
            allTasks.value = [summary as unknown as Task, ...allTasks.value];
            return;
        }

        if (idx === -1 || !summary) {
            scheduleRefresh();
            return;
        }

        const existing = allTasks.value[idx];
        const patch: Partial<Task> = {};
        if (summary.status !== undefined) patch.status = summary.status as Task["status"];
        if (summary.currentStep !== undefined) patch.currentStep = summary.currentStep as number;
        if (summary.findingCount !== undefined) patch.findingCount = summary.findingCount as number;
        if (summary.name !== undefined) patch.name = summary.name as string | null;
        if (summary.goal !== undefined) patch.goal = summary.goal as string;
        if (summary.projectId !== undefined) patch.projectId = summary.projectId as string | null;
        if (summary.reportPath !== undefined) patch.reportPath = summary.reportPath as string | null;
        if (summary.resultSummary !== undefined) patch.resultSummary = summary.resultSummary as string | null;
        if (summary.errorMessage !== undefined) patch.errorMessage = summary.errorMessage as string | null;

        if (eventType === "task.complete") {
            patch.status = "completed";
            if (data.reportPath) patch.reportPath = data.reportPath as string;
            if (data.resultSummary) patch.resultSummary = data.resultSummary as string;
        }

        allTasks.value = [
            ...allTasks.value.slice(0, idx),
            { ...existing, ...patch },
            ...allTasks.value.slice(idx + 1),
        ];
    }

    function connectEventStream(): void {
        if (view.value === "task-detail" && selectedTaskId.value) {
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
            const [summaryResponse] = await Promise.all([
                apiSummary(),
                loadTasks(),
            ]);
            let selectedTaskSnapshot: Task | null = null;
            if (selectedTaskId.value) {
                selectedTaskSnapshot = await apiGetTask(selectedTaskId.value);
            }
            if (selectedTaskSnapshot) {
                allTasks.value = upsertById(allTasks.value, selectedTaskSnapshot, "taskId");
            }
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

    const dialogVisible = computed({
        get: () => dialog.value !== null,
        set: (val: boolean) => {
            if (!val) dialog.value = null;
        },
    });

    return {
        addParam,
        allTasks,
        changeView,
        closeDialog,
        deleteTask,
        deleteModel,
        deleteProject,
        dialog,
        dialogVisible,
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
        onPageChange,
        onPageSizeChange,
        openNewModelDialog,
        openNewProjectDialog,
        openEditTaskDialog,
        openNewTaskDialog,
        page,
        pageSize,
        projectForm,
        projects,
        recentTasks,
        removeParam,
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
        taskLoading,
        taskProjectFilter,
        taskSearchQuery,
        taskStatuses,
        taskStatusFilter,
        testModel,
        total,
        view,
        viewTitle,
    };
}
