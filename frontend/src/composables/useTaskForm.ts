import { getCurrentScope, onScopeDispose, reactive, ref, watch, type Ref } from "vue";
import {
  createTask as apiCreateTask,
  inferTaskLimits,
  updateTask as apiUpdateTask,
} from "../api";
import type { TaskPayload } from "../api";
import type { Project, Task } from "../types";
import {
  clearFormErrors,
  errorMessage,
  isAbortError,
  nullableBoolean,
  nullableText,
  SENTINEL_DEFAULT,
  upsertById,
} from "../utils";
import type { ParamEntry } from "../params";
import { parseParamEntries } from "../params";
import {
  emptyPromptExtensions,
  mergePromptExtensions,
  splitParametersFromPromptExtensions,
  type PromptExtensions,
} from "../promptExtensions";
import { useDebounceFn } from "./useDebounceFn";

// ═══════════════════════════════════════════════════════════════
// 任务类型判别联合 — 表单
// ═══════════════════════════════════════════════════════════════

export interface BlackboxFormConfig {
  startUrl: string;
  maxSteps: number | null;
  timeoutSeconds: number | null;
  captureScreenshots: string;
  parameters: ParamEntry[];
  promptExtensions: PromptExtensions;
}

export interface WhiteboxFormConfig {
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
  const modelConfigId = form.modelConfigId === SENTINEL_DEFAULT ? null : form.modelConfigId || null;

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
  const modelConfigId = form.modelConfigId === SENTINEL_DEFAULT ? null : form.modelConfigId || null;

  const maven = {
    autoDetect: form.whitebox.mavenAutoDetect,
    generateClasspath: form.whitebox.mavenGenerateClasspath,
    classpathFile: form.whitebox.mavenClasspathFile.trim() || null,
    executable: form.whitebox.mavenExecutable.trim() || null,
    settingsXml: form.whitebox.mavenSettingsXml.trim() || null,
    localRepository: form.whitebox.mavenLocalRepository.trim() || null,
    offline: form.whitebox.mavenOffline,
    classpathMode: form.whitebox.mavenClasspathMode as
      | "AUTO"
      | "CACHE_ONLY"
      | "MAVEN"
      | "SOURCE_ONLY",
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
      repoUrl: form.whitebox.sourceType === "git" ? form.whitebox.repoUrl.trim() || null : null,
      sourcePath:
        form.whitebox.sourceType === "local" ? form.whitebox.sourcePath.trim() || null : null,
      ref: form.whitebox.ref.trim() || null,
      scope: form.whitebox.scope,
      targetModules:
        form.whitebox.scope === "modules" ? form.whitebox.targetModules.filter(Boolean) : [],
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
    scope: "all",
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

export function defaultTaskFormState(projectId = ""): TaskFormState {
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
// useTaskForm — 表单状态、校验、payload 构造与 autoFillLimits 推断
// ═══════════════════════════════════════════════════════════════

export function useTaskForm(opts: {
  allTasks: Ref<Task[]>;
  projects: Ref<Project[]>;
  error: Ref<string>;
  message: Ref<string>;
  formErrors: Record<string, string>;
  selectedTaskId: Ref<string | null>;
  selectedTask: Ref<Task | null>;
}) {
  const { allTasks, projects, error, message, formErrors } = opts;

  const taskForm = reactive<TaskFormState>(
    defaultTaskFormState(projects.value[0]?.projectId ?? ""),
  );
  const showTaskDialog = ref(false);

  /** 推断请求的 AbortController；新一次推断先取消旧推断，避免迟到结果覆盖较新输入。 */
  let inferController: AbortController | null = null;
  /** 推断代次：只有最新一次推断能写回表单。 */
  let inferGeneration = 0;

  if (getCurrentScope()) {
    onScopeDispose(() => {
      inferController?.abort();
    });
  }

  async function autoFillLimits(): Promise<void> {
    if (taskForm.editingId) return;
    const trimmed = taskForm.goal.trim();
    if (!trimmed) {
      // 目标被清空：没有新推断要发起，取消在途推断并使其代次失效，
      // 防止迟到结果在用户重新输入前覆盖表单。
      inferController?.abort();
      inferGeneration += 1;
      return;
    }
    // 发起瞬间定格推断输入；响应落地前任何一项变化都说明用户已更新，丢弃结果。
    const goalSnapshot = trimmed;
    const taskTypeSnapshot = taskForm.taskType;
    const startUrlSnapshot = taskTypeSnapshot === "blackbox" ? taskForm.blackbox.startUrl : "";

    inferController?.abort();
    const controller = new AbortController();
    inferController = controller;
    const gen = ++inferGeneration;

    try {
      const limits = await inferTaskLimits(goalSnapshot, startUrlSnapshot || undefined, {
        signal: controller.signal,
      });
      // 二次核对：用户手工修改 goal/startUrl/taskType 或进入编辑态后，不覆盖其输入。
      if (gen !== inferGeneration) return; // 已有更新的推断取代本次
      if (taskForm.editingId) return;
      if (taskForm.taskType !== taskTypeSnapshot) return;
      if (taskForm.goal.trim() !== goalSnapshot) return;
      if (taskTypeSnapshot === "blackbox") {
        if (taskForm.blackbox.startUrl !== startUrlSnapshot) return;
        taskForm.blackbox.maxSteps = limits.maxSteps;
        taskForm.blackbox.timeoutSeconds = limits.timeoutSeconds;
      }
      // taskTypeSnapshot === "whitebox" 时不写黑盒字段（与旧行为一致）。
    } catch (caught) {
      if (gen !== inferGeneration) return; // 旧推断的失败不告警
      if (isAbortError(caught)) return; // 主动取消 / 被新推断取代，不告警
      console.warn("任务参数推断失败：", errorMessage(caught));
    }
  }
  const debouncedAutoFillLimits = useDebounceFn(autoFillLimits, 400);
  watch(
    () => taskForm.goal,
    () => debouncedAutoFillLimits(),
  );
  watch(
    () => (taskForm.taskType === "blackbox" ? taskForm.blackbox.startUrl : ""),
    () => {
      if (taskForm.goal.trim()) debouncedAutoFillLimits();
    },
  );

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
      if (taskForm.whitebox.sourceType === "git" && !taskForm.whitebox.repoUrl.trim()) {
        formErrors.repoUrl = "Git 仓库地址不能为空";
        return;
      }
      if (taskForm.whitebox.sourceType === "local" && !taskForm.whitebox.sourcePath.trim()) {
        formErrors.sourcePath = "服务端源码路径不能为空";
        return;
      }
      if (
        taskForm.whitebox.scope === "modules" &&
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
      opts.selectedTaskId.value = task.taskId;
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

  /** 接收弹窗回传的推断输入（goal/taskType/startUrl），驱动 autoFillLimits。
   * 弹窗内编辑不再直接改写父表单，标量经显式事件同步（F3-3）。 */
  function applyInferInputs(inputs: {
    goal: string;
    taskType: TaskFormState["taskType"];
    startUrl: string;
  }): void {
    if (taskForm.goal !== inputs.goal) taskForm.goal = inputs.goal;
    if (taskForm.taskType !== inputs.taskType) taskForm.taskType = inputs.taskType;
    if (taskForm.blackbox.startUrl !== inputs.startUrl) taskForm.blackbox.startUrl = inputs.startUrl;
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
      scope: wc.scope ?? "all",
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
    const task = targetTask ?? opts.selectedTask.value;
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
      modelConfigId: (task.parameters?.modelConfigId as string) ?? SENTINEL_DEFAULT,
    });
    error.value = "";
    clearFormErrors(formErrors);
    showTaskDialog.value = true;
  }

  function resetTaskForm(): void {
    Object.assign(taskForm, defaultTaskFormState(projects.value[0]?.projectId ?? ""));
  }

  return {
    taskForm,
    showTaskDialog,
    saveTask,
    applyInferInputs,
    openNewTaskDialog,
    openEditTaskDialog,
    resetTaskForm,
  };
}
