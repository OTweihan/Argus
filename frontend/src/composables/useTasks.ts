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

// ═══════════════════════════════════════════════════════════════
// 任务类型判别联合 — 表单
// ═══════════════════════════════════════════════════════════════

interface BlackboxFormConfig {
    startUrl: string;
    maxSteps: number | null;
    timeoutSeconds: number | null;
    captureScreenshots: string;
    parameters: ParamEntry[];
    promptExtensions: PromptExtensions;
}

interface WhiteboxFormConfig {
    sourceType: "git" | "local";
    repoUrl: string;
    sourcePath: string;
    ref: string;
    scope: string;
    targetModules: string[];
    // Maven 常用
    mavenClasspathMode: string;
    mavenOffline: boolean;
    mavenAutoDetect: boolean;
    // Maven 高级
    mavenGenerateClasspath: boolean;
    mavenClasspathFile: string;
    mavenExecutable: string;
    mavenSettingsXml: string;
    mavenLocalRepository: string;
    mavenOfflineTimeoutSeconds: number | null;
    mavenOnlineTimeoutSeconds: number | null;
    mavenPrepareReactorArtifacts: boolean;
}

/** 可辨识联合：通过 taskType 收窄 config 子类型。
 *
 * 注：当前表单使用 TaskFormState（同时持有黑白盒配置），
 * TaskForm 保留用于未来需要类型收窄的场景（如独立的白盒/黑盒表单组件）。
 */
export type TaskForm = {
    editingId: string | null;
    goal: string;
    name: string;
    projectId: string;
    modelConfigId: string;
    taskType: "blackbox";
    config: BlackboxFormConfig;
} | {
    editingId: string | null;
    goal: string;
    name: string;
    projectId: string;
    modelConfigId: string;
    taskType: "whitebox";
    config: WhiteboxFormConfig;
};

/** 表单内部状态 — 同时持有两个子配置以便切换 taskType 时保留输入 */
export interface TaskFormState {
    editingId: string | null;
    goal: string;
    name: string;
    projectId: string;
    modelConfigId: string;
    taskType: "blackbox" | "whitebox";
    blackbox: BlackboxFormConfig;
    whitebox: WhiteboxFormConfig;
}

// ═══════════════════════════════════════════════════════════════
// Payload 构造（类型守卫收窄）
// ═══════════════════════════════════════════════════════════════

function buildBlackboxPayload(form: TaskFormState): TaskPayload {
    const captureScreenshots =
        form.blackbox.captureScreenshots === SENTINEL_DEFAULT
            ? null
            : nullableBoolean(form.blackbox.captureScreenshots as "" | "true" | "false");
    const modelConfigId =
        form.modelConfigId === SENTINEL_DEFAULT ? null : form.modelConfigId || null;

    let parameters: Record<string, unknown>;
    try {
        parameters = parseParamEntries(form.blackbox.parameters);
    } catch (caught) {
        throw new Error(caught instanceof Error ? caught.message : "参数格式无效");
    }
    parameters = mergePromptExtensions(parameters, form.blackbox.promptExtensions);

    return {
        goal: String(form.goal).trim(),
        name: form.name.trim() || null,
        projectId: form.projectId,
        taskType: "blackbox",
        startUrl: nullableText(form.blackbox.startUrl),
        maxSteps: form.blackbox.maxSteps,
        timeoutSeconds: form.blackbox.timeoutSeconds,
        captureScreenshots,
        modelConfigId,
        parameters,
    };
}

function buildWhiteboxPayload(form: TaskFormState): TaskPayload {
    const modelConfigId =
        form.modelConfigId === SENTINEL_DEFAULT ? null : form.modelConfigId || null;

    const maven = {
        autoDetect: form.whitebox.mavenAutoDetect,
        generateClasspath: form.whitebox.mavenGenerateClasspath,
        classpathFile: form.whitebox.mavenClasspathFile.trim() || null,
        executable: form.whitebox.mavenExecutable.trim() || null,
        settingsXml: form.whitebox.mavenSettingsXml.trim() || null,
        localRepository: form.whitebox.mavenLocalRepository.trim() || null,
        offline: form.whitebox.mavenOffline,
        classpathMode: form.whitebox.mavenClasspathMode as
            | "AUTO" | "CACHE_ONLY" | "MAVEN" | "SOURCE_ONLY",
        offlineTimeoutSeconds: form.whitebox.mavenOfflineTimeoutSeconds,
        onlineTimeoutSeconds: form.whitebox.mavenOnlineTimeoutSeconds,
        prepareReactorArtifacts: form.whitebox.mavenPrepareReactorArtifacts,
    };

    return {
        goal: String(form.goal).trim(),
        name: form.name.trim() || null,
        projectId: form.projectId,
        taskType: "whitebox",
        startUrl: null,
        modelConfigId,
        whiteboxConfig: {
            sourceType: form.whitebox.sourceType,
            repoUrl:
                form.whitebox.sourceType === "git"
                    ? form.whitebox.repoUrl.trim() || null
                    : null,
            sourcePath:
                form.whitebox.sourceType === "local"
                    ? form.whitebox.sourcePath.trim() || null
                    : null,
            ref: form.whitebox.ref.trim() || null,
            scope: form.whitebox.scope,
            targetModules:
                form.whitebox.scope === "MODULES"
                    ? form.whitebox.targetModules.filter(Boolean)
                    : [],
            maven,
        },
        // 白盒不携带黑盒字段
        maxSteps: null,
        timeoutSeconds: null,
        captureScreenshots: null,
        parameters: {},
    };
}

// ═══════════════════════════════════════════════════════════════
// 默认值
// ═══════════════════════════════════════════════════════════════

function defaultBlackboxConfig(): BlackboxFormConfig {
    return {
        startUrl: "",
        maxSteps: null,
        timeoutSeconds: null,
        captureScreenshots: SENTINEL_DEFAULT,
        parameters: [],
        promptExtensions: emptyPromptExtensions(),
    };
}

function defaultWhiteboxConfig(): WhiteboxFormConfig {
    return {
        sourceType: "local",
        repoUrl: "",
        sourcePath: "",
        ref: "",
        scope: "ALL",
        targetModules: [],
        mavenClasspathMode: "AUTO",
        mavenOffline: false,
        mavenAutoDetect: true,
        mavenGenerateClasspath: true,
        mavenClasspathFile: "",
        mavenExecutable: "",
        mavenSettingsXml: "",
        mavenLocalRepository: "",
        mavenOfflineTimeoutSeconds: null,
        mavenOnlineTimeoutSeconds: null,
        mavenPrepareReactorArtifacts: false,
    };
}

function defaultTaskFormState(projectId = ""): TaskFormState {
    return {
        editingId: null,
        goal: "",
        name: "",
        projectId,
        modelConfigId: SENTINEL_DEFAULT,
        taskType: "blackbox",
        blackbox: defaultBlackboxConfig(),
        whitebox: defaultWhiteboxConfig(),
    };
}

// ═══════════════════════════════════════════════════════════════
// useTasks
// ═══════════════════════════════════════════════════════════════

export function useTasks(opts: {
    allTasks: Ref<Task[]>;
    projects: Ref<Project[]>;
    models: Ref<ModelConfig[]>;
    error: Ref<string>;
    message: Ref<string>;
    formErrors: Record<string, string>;
    view: Ref<string>;
}) {
    const { allTasks, projects, error, message, formErrors, view } = opts;

    const taskList = useTaskList({ allTasks });
    const taskSelection = useTaskSelection({ allTasks, view, error });

    /* ── 任务表单 ── */

    const taskForm = reactive<TaskFormState>(defaultTaskFormState(projects.value[0]?.projectId ?? ""));
    const showTaskDialog = ref(false);
    const taskStatuses: TaskDisplayStatus[] = [
        "pending", "queued", "running", "completed", "failed", "timeout", "cancelled",
    ];

    async function autoFillLimits(): Promise<void> {
        if (taskForm.editingId) return;
        const trimmed = taskForm.goal.trim();
        if (!trimmed) return;
        try {
            const limits = await inferTaskLimits(trimmed, taskForm.taskType === "blackbox" ? taskForm.blackbox.startUrl : undefined);
            if (taskForm.taskType === "blackbox") {
                taskForm.blackbox.maxSteps = limits.maxSteps;
                taskForm.blackbox.timeoutSeconds = limits.timeoutSeconds;
            }
        } catch (caught) {
            console.warn("任务参数推断失败：", errorMessage(caught));
        }
    }
    const debouncedAutoFillLimits = useDebounceFn(autoFillLimits, 400);
    watch(() => taskForm.goal, () => debouncedAutoFillLimits());
    watch(() => taskForm.taskType === "blackbox" ? taskForm.blackbox.startUrl : "", () => {
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

        const isWhitebox = taskForm.taskType === "whitebox";

        if (!isWhitebox) {
            // 黑盒校验
            const startUrl = taskForm.blackbox.startUrl.trim();
            if (startUrl && !/^https?:\/\/.+/.test(startUrl)) {
                formErrors.startUrl = "请输入合法的 http/https URL";
                return;
            }
        } else {
            // 白盒校验
            if (
                taskForm.whitebox.sourceType === "git" &&
                !taskForm.whitebox.repoUrl.trim()
            ) {
                formErrors.repoUrl = "Git 仓库地址不能为空";
                return;
            }
            if (
                taskForm.whitebox.sourceType === "local" &&
                !taskForm.whitebox.sourcePath.trim()
            ) {
                formErrors.sourcePath = "服务端源码路径不能为空";
                return;
            }
            if (
                taskForm.whitebox.scope === "MODULES" &&
                taskForm.whitebox.targetModules.filter(Boolean).length === 0
            ) {
                formErrors.targetModules = "按模块分析时需指定至少一个目标模块";
                return;
            }
        }

        try {
            const payload: TaskPayload = isWhitebox
                ? buildWhiteboxPayload(taskForm)
                : buildBlackboxPayload(taskForm);

            const isEditing = Boolean(taskForm.editingId);
            const task = taskForm.editingId
                ? await apiUpdateTask(taskForm.editingId, payload)
                : await apiCreateTask(payload);
            allTasks.value = upsertById(allTasks.value, task, "taskId");
            taskSelection.selectedTaskId.value = task.taskId;
            showTaskDialog.value = false;
            resetTaskForm();
            message.value = isEditing ? "任务已更新。" : "任务已创建。";
            error.value = "";
        } catch (caught) {
            error.value = errorMessage(caught);
            message.value = "";
        }
    }

    /* ── 表单辅助 ── */

    function addParam(): void {
        if (taskForm.taskType === "blackbox") {
            taskForm.blackbox.parameters.push({ key: "", value: "" });
        }
    }

    function removeParam(index: number): void {
        if (taskForm.taskType === "blackbox") {
            taskForm.blackbox.parameters.splice(index, 1);
        }
    }

    function openNewTaskDialog(): void {
        resetTaskForm();
        error.value = "";
        clearFormErrors(formErrors);
        showTaskDialog.value = true;
    }

    /** 从 Task.whiteboxConfigView 恢复白盒表单字段。
     *
     * sourcePathDisplay / repoUrlDisplay 是展示用脱敏值（如 .../foo/bar），
     * 编辑时必须使用 sourcePath / repoUrl 真实值，否则保存后真实路径被覆盖。 */
    function _restoreWhiteboxForm(task: Task): void {
        const view = task.whiteboxConfigView;
        if (!view || view.status !== "VALID" || !view.config) return;
        const wc = view.config;
        taskForm.taskType = "whitebox";
        Object.assign(taskForm.whitebox, {
            sourceType: (wc.sourceType as "git" | "local") || "local",
            repoUrl: wc.repoUrl ?? "",
            sourcePath: wc.sourcePath ?? "",
            ref: wc.ref ?? "",
            scope: wc.scope ?? "ALL",
            targetModules: wc.targetModules ?? [],
        });
        if (wc.maven) {
            const m = wc.maven;
            Object.assign(taskForm.whitebox, {
                mavenClasspathMode: m.classpathMode ?? "AUTO",
                mavenOffline: m.offline ?? false,
                mavenAutoDetect: m.autoDetect ?? true,
                // 高级字段：使用编辑级真实值
                mavenGenerateClasspath: m.generateClasspath ?? true,
                mavenClasspathFile: m.classpathFile ?? "",
                mavenExecutable: m.executable ?? "",
                mavenSettingsXml: m.settingsXml ?? "",
                mavenLocalRepository: m.localRepository ?? "",
                mavenOfflineTimeoutSeconds: m.offlineTimeoutSeconds ?? null,
                mavenOnlineTimeoutSeconds: m.onlineTimeoutSeconds ?? null,
                mavenPrepareReactorArtifacts: m.prepareReactorArtifacts ?? false,
            });
        }
    }

    function openEditTaskDialog(targetTask?: Task): void {
        const task = targetTask ?? taskSelection.selectedTask.value;
        if (!task) return;
        const projectId = task.projectId ?? projects.value[0]?.projectId ?? "";
        const isWhitebox = task.taskType === "whitebox";

        // 重置到默认
        resetTaskForm();

        if (isWhitebox) {
            _restoreWhiteboxForm(task);
        } else {
            const { rest, promptExtensions } = splitParametersFromPromptExtensions(task.parameters);
            taskForm.taskType = "blackbox";
            Object.assign(taskForm.blackbox, {
                startUrl: task.startUrl ?? "",
                maxSteps: task.maxSteps,
                timeoutSeconds: task.timeoutSeconds,
                captureScreenshots: task.captureScreenshots ? "true" : "false",
                parameters: Object.entries(rest)
                    .filter(([k]) => k !== "modelConfigId")
                    .map(([key, value]) => ({ key, value: String(value) })),
                promptExtensions,
            });
        }

        Object.assign(taskForm, {
            editingId: task.taskId,
            goal: task.goal,
            name: task.name ?? "",
            projectId,
            modelConfigId:
                ((task.parameters?.modelConfigId) as string) ?? SENTINEL_DEFAULT,
        });
        error.value = "";
        clearFormErrors(formErrors);
        showTaskDialog.value = true;
    }

    function resetTaskForm(): void {
        Object.assign(taskForm, defaultTaskFormState(projects.value[0]?.projectId ?? ""));
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

type TaskDisplayStatus = "pending" | "queued" | "running" | "completed" | "failed" | "timeout" | "cancelled";
