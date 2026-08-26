import { computed, onUnmounted, ref, watch, type Ref } from "vue";

import {
  cancelRegressionRun,
  createRegressionCase,
  createRegressionRun,
  deleteRegressionCase,
  getRegressionBaseline,
  getRegressionRun,
  listRegressionCases,
  listRegressionRuns,
  setRegressionBaseline,
  updateRegressionCase,
  type RegressionCaseInfo,
  type RegressionCasePayload,
  type RegressionRunDetailInfo,
  type RegressionRunInfo,
} from "../api/regression";
import { errorMessage } from "../utils";

const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled"]);
const DETAIL_POLL_INTERVAL_MS = 3000;

export interface RegressionCaseForm {
  editingId: string | null;
  name: string;
  taskType: "blackbox" | "whitebox";
  goal: string;
  startUrl: string;
  maxSteps: number | null;
  timeoutSeconds: number | null;
  captureScreenshots: boolean;
  parametersText: string;
  enabled: boolean;
  displayOrder: number;
}

function defaultCaseForm(): RegressionCaseForm {
  return {
    editingId: null,
    name: "",
    taskType: "blackbox",
    goal: "",
    startUrl: "",
    maxSteps: null,
    timeoutSeconds: null,
    captureScreenshots: true,
    parametersText: "{}",
    enabled: true,
    displayOrder: 0,
  };
}

/** 回归闭环页面用例：项目切换 → 用例管理 → 批次发起/详情轮询 → 基线。 */
export function useRegression(opts: { error: Ref<string>; message: Ref<string> }) {
  const { error, message } = opts;

  const selectedProjectId = ref<string>("");
  const cases = ref<RegressionCaseInfo[]>([]);
  const casesLoading = ref(false);
  const runs = ref<RegressionRunInfo[]>([]);
  const runsTotal = ref(0);
  const runsLoading = ref(false);
  const baselineRunId = ref<string | null>(null);

  const showCaseDialog = ref(false);
  const caseForm = ref<RegressionCaseForm>(defaultCaseForm());
  const caseSaving = ref(false);
  const startingRun = ref(false);

  const detail = ref<RegressionRunDetailInfo | null>(null);
  const showDetail = ref(false);
  const detailLoading = ref(false);
  let detailTimer: number | null = null;

  const selectedProjectHasCases = computed(() => cases.value.length > 0);

  /* ── 数据加载 ── */

  async function loadCases(): Promise<void> {
    if (!selectedProjectId.value) return;
    casesLoading.value = true;
    try {
      const res = await listRegressionCases(selectedProjectId.value);
      cases.value = res.cases ?? [];
    } catch (caught) {
      error.value = errorMessage(caught);
    } finally {
      casesLoading.value = false;
    }
  }

  async function loadRuns(): Promise<void> {
    if (!selectedProjectId.value) return;
    runsLoading.value = true;
    try {
      const res = await listRegressionRuns(selectedProjectId.value, { offset: 0, limit: 50 });
      runs.value = res.runs ?? [];
      runsTotal.value = res.total ?? 0;
    } catch (caught) {
      error.value = errorMessage(caught);
    } finally {
      runsLoading.value = false;
    }
  }

  async function loadBaseline(): Promise<void> {
    if (!selectedProjectId.value) return;
    try {
      const res = await getRegressionBaseline(selectedProjectId.value);
      baselineRunId.value = res.baselineRunId ?? null;
    } catch (caught) {
      error.value = errorMessage(caught);
    }
  }

  function selectProject(projectId: string): void {
    if (selectedProjectId.value === projectId) return;
    selectedProjectId.value = projectId;
    closeDetail();
  }

  // 项目切换后统一刷新三块数据
  watch(selectedProjectId, () => {
    void loadCases();
    void loadRuns();
    void loadBaseline();
  });

  /* ── 用例管理 ── */

  function openNewCaseDialog(): void {
    caseForm.value = defaultCaseForm();
    error.value = "";
    showCaseDialog.value = true;
  }

  function openEditCaseDialog(info: RegressionCaseInfo): void {
    let parametersText = "{}";
    try {
      parametersText = JSON.stringify(info.parameters ?? {}, null, 2);
    } catch {
      parametersText = "{}";
    }
    caseForm.value = {
      editingId: info.caseId,
      name: info.name,
      taskType: info.taskType === "whitebox" ? "whitebox" : "blackbox",
      goal: info.goal,
      startUrl: info.startUrl ?? "",
      maxSteps: info.maxSteps ?? null,
      timeoutSeconds: info.timeoutSeconds ?? null,
      captureScreenshots: info.captureScreenshots,
      parametersText,
      enabled: info.enabled,
      displayOrder: info.displayOrder ?? 0,
    };
    error.value = "";
    showCaseDialog.value = true;
  }

  function buildCasePayload(form: RegressionCaseForm): Partial<RegressionCasePayload> {
    let parameters: Record<string, unknown> = {};
    const text = form.parametersText.trim();
    if (text) {
      try {
        const parsed = JSON.parse(text) as unknown;
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          throw new Error("parameters 必须是 JSON 对象");
        }
        parameters = parsed as Record<string, unknown>;
      } catch (caught) {
        throw new Error(
          `parameters 解析失败：${caught instanceof Error ? caught.message : String(caught)}`,
        );
      }
    }
    const payload: Partial<RegressionCasePayload> = {
      name: form.name.trim(),
      taskType: form.taskType,
      goal: form.goal.trim(),
      startUrl: form.startUrl.trim() || undefined,
      captureScreenshots: form.captureScreenshots,
      parameters,
      enabled: form.enabled,
      displayOrder: Number(form.displayOrder) || 0,
    };
    if (form.maxSteps !== null) payload.maxSteps = form.maxSteps;
    if (form.timeoutSeconds !== null) payload.timeoutSeconds = form.timeoutSeconds;
    return payload;
  }

  async function saveCase(): Promise<boolean> {
    const form = caseForm.value;
    if (!form.name.trim()) {
      error.value = "用例名称不能为空。";
      return false;
    }
    if (!form.goal.trim()) {
      error.value = "测试目标（goal）不能为空。";
      return false;
    }
    let payload: Partial<RegressionCasePayload>;
    try {
      payload = buildCasePayload(form);
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught);
      return false;
    }
    caseSaving.value = true;
    try {
      if (form.editingId) {
        await updateRegressionCase(form.editingId, payload);
        message.value = "用例已更新。";
      } else {
        await createRegressionCase(selectedProjectId.value, payload);
        message.value = "用例已创建。";
      }
      error.value = "";
      showCaseDialog.value = false;
      await loadCases();
      return true;
    } catch (caught) {
      error.value = errorMessage(caught);
      return false;
    } finally {
      caseSaving.value = false;
    }
  }

  async function removeCase(info: RegressionCaseInfo): Promise<void> {
    try {
      await deleteRegressionCase(info.caseId);
      message.value = "用例已删除。";
      await loadCases();
    } catch (caught) {
      error.value = errorMessage(caught);
    }
  }

  async function toggleEnabled(info: RegressionCaseInfo): Promise<void> {
    try {
      await updateRegressionCase(info.caseId, { enabled: !info.enabled });
      await loadCases();
    } catch (caught) {
      error.value = errorMessage(caught);
    }
  }

  /* ── 批次 ── */

  async function startRun(): Promise<void> {
    if (!selectedProjectId.value) return;
    startingRun.value = true;
    try {
      const run = await createRegressionRun(selectedProjectId.value);
      message.value = `批次已创建：${run.runId}`;
      error.value = "";
      await loadRuns();
      await openRunDetail(run.runId);
    } catch (caught) {
      error.value = errorMessage(caught);
    } finally {
      startingRun.value = false;
    }
  }

  async function cancelCurrentRun(): Promise<void> {
    const runId = detail.value?.run?.runId;
    if (!runId) return;
    try {
      await cancelRegressionRun(runId);
      message.value = "批次已取消。";
      await refreshDetail();
      await loadRuns();
    } catch (caught) {
      error.value = errorMessage(caught);
    }
  }

  /* ── 批次详情与轮询 ── */

  function stopDetailPolling(): void {
    if (detailTimer !== null) {
      window.clearInterval(detailTimer);
      detailTimer = null;
    }
  }

  async function refreshDetail(): Promise<void> {
    const runId = detail.value?.run?.runId;
    if (!runId) return;
    detailLoading.value = true;
    try {
      detail.value = await getRegressionRun(runId);
    } catch (caught) {
      error.value = errorMessage(caught);
    } finally {
      detailLoading.value = false;
    }
    scheduleDetailPolling();
  }

  function scheduleDetailPolling(): void {
    stopDetailPolling();
    const status = detail.value?.run?.status;
    if (!status || TERMINAL_RUN_STATUSES.has(status)) return;
    detailTimer = window.setInterval(() => {
      void pollOnce();
    }, DETAIL_POLL_INTERVAL_MS);
  }

  async function pollOnce(): Promise<void> {
    const runId = detail.value?.run?.runId;
    if (!runId) return;
    try {
      const next = await getRegressionRun(runId);
      const before = detail.value?.run?.status;
      detail.value = next;
      if (before !== next.run.status && TERMINAL_RUN_STATUSES.has(next.run.status)) {
        message.value =
          next.run.gateResult === "passed" ? "批次通过质量门禁。" : "批次未通过质量门禁。";
        await loadRuns();
        await loadBaseline();
      }
      scheduleDetailPolling();
    } catch {
      // 轮询失败静默重试；终态以查询接口为准
    }
  }

  async function openRunDetail(runId: string): Promise<void> {
    showDetail.value = true;
    detail.value = null;
    detailLoading.value = true;
    try {
      detail.value = await getRegressionRun(runId);
    } catch (caught) {
      error.value = errorMessage(caught);
    } finally {
      detailLoading.value = false;
    }
    scheduleDetailPolling();
  }

  function closeDetail(): void {
    stopDetailPolling();
    showDetail.value = false;
    detail.value = null;
  }

  /* ── 基线 ── */

  async function markBaseline(run: RegressionRunInfo): Promise<void> {
    try {
      await setRegressionBaseline(run.projectId, run.runId);
      message.value = `已将批次 ${run.runId} 设为基线。`;
      await loadBaseline();
      await loadRuns();
    } catch (caught) {
      error.value = errorMessage(caught);
    }
  }

  onUnmounted(stopDetailPolling);

  return {
    selectedProjectId,
    selectedProjectHasCases,
    cases,
    casesLoading,
    runs,
    runsTotal,
    runsLoading,
    baselineRunId,
    showCaseDialog,
    caseForm,
    caseSaving,
    startingRun,
    detail,
    showDetail,
    detailLoading,
    selectProject,
    loadCases,
    loadRuns,
    loadBaseline,
    openNewCaseDialog,
    openEditCaseDialog,
    saveCase,
    removeCase,
    toggleEnabled,
    startRun,
    cancelCurrentRun,
    openRunDetail,
    closeDetail,
    refreshDetail,
    markBaseline,
  };
}

export type RegressionStore = ReturnType<typeof useRegression>;
