import {computed, reactive, ref, type Ref, watch} from "vue";
import {ElMessageBox} from "element-plus";
import {
    createTask as apiCreateTask,
    deleteTask as apiDeleteTask,
    getTask as apiGetTask,
    getTaskReportJson as apiGetTaskReportJson,
    inferTaskLimits,
    listTasks as apiListTasks,
    startTask as apiStartTask,
    updateTask as apiUpdateTask,
} from "../api";
import type {TaskPayload} from "../api";
import type {ModelConfig, Project, ReportData, Task, TaskDisplayStatus} from "../types";
import {errorMessage, nullableBoolean, nullableText, upsertById} from "../utils";

interface ParamEntry {
    key: string;
    value: string;
}

interface TaskForm {
    editingId: string | null;
    goal: string;
    name: string;
    projectId: string;
    startUrl: string;
    maxSteps: number | null;
    timeoutSeconds: number | null;
    captureScreenshots: string;
    modelConfigId: string;
    parameters: ParamEntry[];
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

    let goalTimer: number | null = null;
    async function autoFillLimits(): Promise<void> {
        if (taskForm.editingId) return;
        const trimmed = taskForm.goal.trim();
        if (!trimmed) return;
        try {
            const limits = await inferTaskLimits(trimmed, taskForm.startUrl || undefined);
            taskForm.maxSteps = limits.maxSteps;
            taskForm.timeoutSeconds = limits.timeoutSeconds;
        } catch {
            // 推断失败时静默忽略，保留现有值
        }
    }
    watch(
        () => taskForm.goal,
        () => {
            if (goalTimer !== null) clearTimeout(goalTimer);
            goalTimer = window.setTimeout(autoFillLimits, 400);
        },
    );
    watch(
        () => taskForm.startUrl,
        () => {
            if (taskForm.goal.trim()) {
                if (goalTimer !== null) clearTimeout(goalTimer);
                goalTimer = window.setTimeout(autoFillLimits, 400);
            }
        },
    );

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

    async function deleteTask(task: Task): Promise<void> {
        if (task.status !== "pending" || task.schedulerStatus) return;
        try {
            await ElMessageBox.confirm("确认删除这个任务？", "警告", {
                confirmButtonText: "删除",
                cancelButtonText: "取消",
                type: "warning",
            });
            await apiDeleteTask(task.taskId);
            allTasks.value = allTasks.value.filter((item) => item.taskId !== task.taskId);
            total.value = Math.max(0, total.value - 1);
            if (selectedTaskId.value === task.taskId) {
                selectedTaskId.value = null;
            }
            message.value = "任务已删除。";
            error.value = "";
            if (allTasks.value.length === 0 && total.value > 0 && page.value > 1) {
                page.value -= 1;
            }
            await loadTasks();
        } catch (caught) {
            if (caught === "cancel") return;
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
        const startUrl = taskForm.startUrl.trim();
        if (startUrl && !/^https?:\/\/.+/.test(startUrl)) {
            formErrors.startUrl = "请输入合法的 http/https URL";
            return;
        }
        let parameters: Record<string, unknown>;
        try {
            parameters = parseParamEntries(taskForm.parameters);
        } catch (caught) {
            formErrors.taskParameters = caught instanceof Error ? caught.message : "参数格式无效";
            return;
        }
        try {
            const modelConfigId = taskForm.modelConfigId === "__default__" ? null : taskForm.modelConfigId || null;
            const captureScreenshots = taskForm.captureScreenshots === "__default__" ? null : nullableBoolean(taskForm.captureScreenshots as "" | "true" | "false");
            const payload: TaskPayload = {
                goal: String(taskForm.goal).trim(),
                name: taskForm.name.trim() || null,
                projectId: taskForm.projectId,
                startUrl: nullableText(taskForm.startUrl),
                taskType: "blackbox",
                maxSteps: taskForm.maxSteps,
                timeoutSeconds: taskForm.timeoutSeconds,
                captureScreenshots,
                modelConfigId,
                parameters,
            };
            const isEditing = Boolean(taskForm.editingId);
            const task = taskForm.editingId
                ? await apiUpdateTask(taskForm.editingId, payload)
                : await apiCreateTask(payload);
            allTasks.value = upsertById(allTasks.value, task, "taskId");
            selectedTaskId.value = task.taskId;
            showTaskDialog.value = false;
            resetTaskForm();
            connectEventStream();
            message.value = isEditing ? "任务已更新。" : "任务已创建。";
            error.value = "";
        } catch (caught) {
            error.value = errorMessage(caught);
            message.value = "";
        }
    }

    function addParam(): void {
        taskForm.parameters.push({key: "", value: ""});
    }

    function removeParam(index: number): void {
        taskForm.parameters.splice(index, 1);
    }

    function openNewTaskDialog(): void {
        resetTaskForm();
        error.value = "";
        clearFormErrors();
        showTaskDialog.value = true;
    }

    function openEditTaskDialog(targetTask?: Task): void {
        const task = targetTask ?? selectedTask.value;
        if (!task) return;
        const projectId = task.projectId ?? projects.value[0]?.projectId ?? "";
        Object.assign(taskForm, {
            editingId: task.taskId,
            goal: task.goal,
            name: task.name ?? "",
            projectId,
            startUrl: task.startUrl ?? "",
            maxSteps: task.maxSteps,
            timeoutSeconds: task.timeoutSeconds,
            captureScreenshots: task.captureScreenshots ? "true" : "false",
            modelConfigId: (task.parameters?.modelConfigId as string) ?? "__default__",
            parameters: task.parameters ? Object.entries(task.parameters)
                .filter(([k]) => k !== "modelConfigId")
                .map(([key, value]) => ({key, value: String(value)})) : [],
        });
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
        deleteTask,
        saveTask,
        addParam,
        removeParam,
        openNewTaskDialog,
        openEditTaskDialog,
        resetTaskForm,
    };
}

function parseParamEntries(entries: ParamEntry[]): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    for (const entry of entries) {
        const key = entry.key.trim();
        if (!key) continue;
        if (key in result) {
            throw new Error(`参数键重复：${key}`);
        }
        result[key] = entry.value;
    }
    return result;
}

function defaultTaskForm(projectId = ""): TaskForm {
    return {
        editingId: null,
        goal: "",
        name: "",
        projectId,
        startUrl: "",
        maxSteps: null,
        timeoutSeconds: null,
        captureScreenshots: "__default__",
        modelConfigId: "__default__",
        parameters: [],
    };
}
