import {computed, reactive, ref, watch, type Ref} from "vue";
import {
    listTasks as apiListTasks,
    getTask as apiGetTask,
    createTask as apiCreateTask,
    startTask as apiStartTask,
    getTaskReportJson as apiGetTaskReportJson,
} from "../api";
import type {ModelConfig, Project, ReportData, Task, TaskDisplayStatus} from "../types";
import {errorMessage, nullableBoolean, nullableText, parseJsonObject, upsertById} from "../utils";

interface TaskForm {
    goal: string;
    projectId: string;
    startUrl: string;
    maxSteps: number | null;
    timeoutSeconds: number | null;
    captureScreenshots: "" | "true" | "false";
    modelConfigId: string;
    parameters: string;
}

export function useTasks(opts: {
    allTasks: Ref<Task[]>;
    projects: Ref<Project[]>;
    models: Ref<ModelConfig[]>;
    error: Ref<string>;
    message: Ref<string>;
    formErrors: Record<string, string>;
    view: Ref<string>;
    connectEventStream: () => void;
}) {
    const {allTasks, projects, models, error, message, formErrors, view, connectEventStream} = opts;
    const taskForm = reactive<TaskForm>(defaultTaskForm(projects.value[0]?.projectId ?? ""));
    const showTaskDialog = ref(false);
    const taskStatusFilter = ref<TaskDisplayStatus | "">("");
    const taskProjectFilter = ref("");
    const taskSearchQuery = ref("");
    const selectedTaskId = ref<string | null>(null);
    const reportData = ref<ReportData | null>(null);
    const reportLoading = ref(false);
    const page = ref(1);
    const pageSize = ref(20);
    const total = ref(0);
    const taskLoading = ref(false);

    const selectedTask = computed(() => {
        if (!selectedTaskId.value) return null;
        return allTasks.value.find((task) => task.taskId === selectedTaskId.value) ?? null;
    });

    const taskStatuses: TaskDisplayStatus[] = [
        "pending", "queued", "running", "completed", "failed", "timeout", "cancelled",
    ];

    async function loadTasks(): Promise<void> {
        taskLoading.value = true;
        try {
            const status = taskStatusFilter.value || undefined;
            const res = await apiListTasks({
                status,
                projectId: taskProjectFilter.value || undefined,
                q: taskSearchQuery.value.trim() || undefined,
                offset: (page.value - 1) * pageSize.value,
                limit: pageSize.value,
            });
            allTasks.value = res.tasks;
            total.value = res.total;
        } finally {
            taskLoading.value = false;
        }
    }

    function onPageChange(newPage: number): void {
        page.value = newPage;
        loadTasks();
    }

    function onPageSizeChange(newSize: number): void {
        pageSize.value = newSize;
        page.value = 1;
        loadTasks();
    }

    let searchTimer: number | null = null;
    watch(taskSearchQuery, () => {
        if (searchTimer !== null) clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => {
            page.value = 1;
            loadTasks();
        }, 300);
    });

    watch([taskStatusFilter, taskProjectFilter], () => {
        page.value = 1;
        loadTasks();
    });

    async function selectTask(taskId: string): Promise<void> {
        try {
            selectedTaskId.value = taskId;
            view.value = "task-detail";
            reportData.value = null;
            reportLoading.value = true;
            const task = await apiGetTask(taskId);
            allTasks.value = upsertById(allTasks.value, task, "taskId");
            if (task.reportPath) {
                const data = await apiGetTaskReportJson(taskId);
                reportData.value = data;
            }
            connectEventStream();
        } catch (caught) {
            error.value = errorMessage(caught);
        } finally {
            reportLoading.value = false;
        }
    }

    function goBackToTasks(): void {
        selectedTaskId.value = null;
        view.value = "tasks";
        connectEventStream();
    }

    async function startTask(taskId: string): Promise<void> {
        try {
            const result = await apiStartTask(taskId);
            allTasks.value = upsertById(allTasks.value, result.task, "taskId");
            message.value = `任务已入队：${result.schedulerStatus}`;
            error.value = "";
        } catch (caught) {
            error.value = errorMessage(caught);
            message.value = "";
        }
    }

    async function saveTask(): Promise<void> {
        clearFormErrors();
        if (!String(taskForm.goal).trim()) {
            formErrors.goal = "目标不能为空";
            return;
        }
        let parameters: Record<string, unknown>;
        try {
            parameters = parseJsonObject(taskForm.parameters, "参数 JSON");
        } catch {
            formErrors.taskParameters = "必须为合法 JSON";
            return;
        }
        try {
            const task = await apiCreateTask({
                goal: String(taskForm.goal).trim(),
                projectId: taskForm.projectId,
                startUrl: nullableText(taskForm.startUrl),
                taskType: "blackbox",
                maxSteps: taskForm.maxSteps,
                timeoutSeconds: taskForm.timeoutSeconds,
                captureScreenshots: nullableBoolean(taskForm.captureScreenshots),
                modelConfigId: nullableText(taskForm.modelConfigId),
                parameters,
            });
            allTasks.value = upsertById(allTasks.value, task, "taskId");
            selectedTaskId.value = task.taskId;
            showTaskDialog.value = false;
            resetTaskForm();
            connectEventStream();
            message.value = "任务已创建。";
            error.value = "";
        } catch (caught) {
            error.value = errorMessage(caught);
            message.value = "";
        }
    }

    function openNewTaskDialog(): void {
        resetTaskForm();
        error.value = "";
        clearFormErrors();
        showTaskDialog.value = true;
    }

    function resetTaskForm(): void {
        Object.assign(taskForm, defaultTaskForm(projects.value[0]?.projectId ?? ""));
    }

    function clearFormErrors(): void {
        for (const key of Object.keys(formErrors)) {
            delete formErrors[key];
        }
    }

    return {
        taskForm,
        showTaskDialog,
        taskStatusFilter,
        taskProjectFilter,
        taskSearchQuery,
        selectedTaskId,
        reportData,
        reportLoading,
        selectedTask,
        page,
        pageSize,
        total,
        taskLoading,
        taskStatuses,
        loadTasks,
        onPageChange,
        onPageSizeChange,
        selectTask,
        goBackToTasks,
        startTask,
        saveTask,
        openNewTaskDialog,
        resetTaskForm,
    };
}

function defaultTaskForm(projectId = ""): TaskForm {
    return {
        goal: "",
        projectId,
        startUrl: "",
        maxSteps: null,
        timeoutSeconds: null,
        captureScreenshots: "",
        modelConfigId: "",
        parameters: "{}",
    };
}
