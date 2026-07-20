import { reactive, ref, watch, type Ref } from "vue";
import { ElMessageBox } from "element-plus";
import {
    createTask as apiCreateTask,
    deleteTask as apiDeleteTask,
    inferTaskLimits,
    restartTask as apiRestartTask,
    startTask as apiStartTask,
    updateTask as apiUpdateTask,
} from "../api";
import type { TaskPayload } from "../api";
import type { ModelConfig, Project, Task } from "../types";
import { clearFormErrors, errorMessage, nullableBoolean, nullableText, SENTINEL_DEFAULT, upsertById } from "../utils";
import type { ParamEntry } from "../params";
import { parseParamEntries } from "../params";
import {
    emptyPromptExtensions,
    mergePromptExtensions,
    splitParametersFromPromptExtensions,
    type PromptExtensions,
} from "../promptExtensions";
import { useDebounceFn } from "./useDebounceFn";
import { useTaskList } from "./useTaskList";
import { useTaskSelection } from "./useTaskSelection";

export interface TaskForm {
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
    promptExtensions: PromptExtensions;
}

/**
 * 本 composable 不接收 `connectEventStream` 回调。任务创建/选中后由编排层
 * `useConsoleApp` 通过 `watch([view, selectedTaskId])` 主动驱动 WS 重连，
 * 避免早期版本的"holder ref"鸡生蛋 hack。
 */
export function useTasks(opts: {
    allTasks: Ref<Task[]>;
    projects: Ref<Project[]>;
    models: Ref<ModelConfig[]>;
    error: Ref<string>;
    message: Ref<string>;
    formErrors: Record<string, string>;
    view: Ref<string>;
}) {
    // models 留在 opts 类型里以保持调用方契约（useConsoleApp 仍按原 shape 传入），
    // 但当前实现不直接消费它（任务模型选择由 modelDomain 负责）。
    const { allTasks, projects, error, message, formErrors, view } = opts;

    const taskList = useTaskList({ allTasks });
    const taskSelection = useTaskSelection({ allTasks, view, error });

    /* ── 任务表单 ── */

    const taskForm = reactive<TaskForm>(defaultTaskForm(projects.value[0]?.projectId ?? ""));
    const showTaskDialog = ref(false);
    const taskStatuses: TaskDisplayStatus[] = [
        "pending", "queued", "running", "completed", "failed", "timeout", "cancelled",
    ];

    async function autoFillLimits(): Promise<void> {
        if (taskForm.editingId) return;
        const trimmed = taskForm.goal.trim();
        if (!trimmed) return;
        try {
            const limits = await inferTaskLimits(trimmed, taskForm.startUrl || undefined);
            taskForm.maxSteps = limits.maxSteps;
            taskForm.timeoutSeconds = limits.timeoutSeconds;
        } catch (caught) {
            console.warn("任务参数推断失败：", errorMessage(caught));
        }
    }
    // goal / startUrl 两个 watcher 共享同一 debounced 函数：任意一处修改
    // 都重置等待计时器，组件卸载时由 useDebounceFn 自动 cancel。
    const debouncedAutoFillLimits = useDebounceFn(autoFillLimits, 400);
    watch(() => taskForm.goal, () => debouncedAutoFillLimits());
    watch(() => taskForm.startUrl, () => {
        if (taskForm.goal.trim()) debouncedAutoFillLimits();
    });

    /* ── 任务操作 ── */

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

    async function retryTask(taskId: string): Promise<void> {
        try {
            await apiRestartTask(taskId);
            await taskList.loadTasks();
            message.value = "任务已重新入队。";
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
            taskList.total.value = Math.max(0, taskList.total.value - 1);
            if (taskSelection.selectedTaskId.value === task.taskId) {
                taskSelection.selectedTaskId.value = null;
            }
            message.value = "任务已删除。";
            error.value = "";
            if (allTasks.value.length === 0 && taskList.total.value > 0 && taskList.page.value > 1) {
                taskList.page.value -= 1;
            }
            await taskList.loadTasks();
        } catch (caught) {
            if (caught === "cancel") return;
            error.value = errorMessage(caught);
            message.value = "";
        }
    }

    async function saveTask(): Promise<void> {
        clearFormErrors(formErrors);
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
        parameters = mergePromptExtensions(parameters, taskForm.promptExtensions);
        try {
            const modelConfigId = taskForm.modelConfigId === SENTINEL_DEFAULT ? null : taskForm.modelConfigId || null;
            const captureScreenshots = taskForm.captureScreenshots === SENTINEL_DEFAULT ? null : nullableBoolean(taskForm.captureScreenshots as "" | "true" | "false");
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
            taskSelection.selectedTaskId.value = task.taskId;
            showTaskDialog.value = false;
            resetTaskForm();
            // WS 重连由编排层 watch(selectedTaskId) 自动触发，无需手动调。
            message.value = isEditing ? "任务已更新。" : "任务已创建。";
            error.value = "";
        } catch (caught) {
            error.value = errorMessage(caught);
            message.value = "";
        }
    }

    /* ── 表单辅助 ── */

    function addParam(): void {
        taskForm.parameters.push({key: "", value: ""});
    }

    function removeParam(index: number): void {
        taskForm.parameters.splice(index, 1);
    }

    function openNewTaskDialog(): void {
        resetTaskForm();
        error.value = "";
        clearFormErrors(formErrors);
        showTaskDialog.value = true;
    }

    function openEditTaskDialog(targetTask?: Task): void {
        const task = targetTask ?? taskSelection.selectedTask.value;
        if (!task) return;
        const projectId = task.projectId ?? projects.value[0]?.projectId ?? "";
        const {rest, promptExtensions} = splitParametersFromPromptExtensions(task.parameters);
        Object.assign(taskForm, {
            editingId: task.taskId,
            goal: task.goal,
            name: task.name ?? "",
            projectId,
            startUrl: task.startUrl ?? "",
            maxSteps: task.maxSteps,
            timeoutSeconds: task.timeoutSeconds,
            captureScreenshots: task.captureScreenshots ? "true" : "false",
            modelConfigId: (rest.modelConfigId as string) ?? SENTINEL_DEFAULT,
            parameters: Object.entries(rest)
                .filter(([k]) => k !== "modelConfigId")
                .map(([key, value]) => ({key, value: String(value)})),
            promptExtensions,
        });
        error.value = "";
        clearFormErrors(formErrors);
        showTaskDialog.value = true;
    }

    function resetTaskForm(): void {
        Object.assign(taskForm, defaultTaskForm(projects.value[0]?.projectId ?? ""));
    }

    return {
        /* task list */
        ...taskList,
        /* task selection */
        ...taskSelection,
        /* form */
        taskForm,
        showTaskDialog,
        taskStatuses,
        /* actions */
        startTask,
        retryTask,
        deleteTask,
        saveTask,
        addParam,
        removeParam,
        openNewTaskDialog,
        openEditTaskDialog,
        resetTaskForm,
    };
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
        captureScreenshots: SENTINEL_DEFAULT,
        modelConfigId: SENTINEL_DEFAULT,
        parameters: [],
        promptExtensions: emptyPromptExtensions(),
    };
}

type TaskDisplayStatus = "pending" | "queued" | "running" | "completed" | "failed" | "timeout" | "cancelled";
