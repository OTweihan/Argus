import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

// mock API 层：composable 只编排状态，不触网
vi.mock("../../api/regression", () => ({
  listRegressionCases: vi.fn().mockResolvedValue({ total: 0, cases: [] }),
  createRegressionCase: vi.fn(),
  updateRegressionCase: vi.fn(),
  deleteRegressionCase: vi.fn(),
  createRegressionRun: vi.fn(),
  listRegressionRuns: vi.fn().mockResolvedValue({ total: 0, runs: [], offset: 0, limit: 50 }),
  getRegressionRun: vi.fn(),
  cancelRegressionRun: vi.fn(),
  getRegressionBaseline: vi.fn().mockResolvedValue({ baselineRunId: null }),
  setRegressionBaseline: vi.fn(),
}));

import {
  createRegressionCase,
  deleteRegressionCase,
  getRegressionBaseline,
  getRegressionRun,
  listRegressionCases,
  listRegressionRuns,
} from "../../api/regression";
import { useRegression } from "../useRegression";

const error = ref("");
const message = ref("");

function makeStore() {
  const store = useRegression({ error, message });
  store.selectProject("proj-1");
  return store;
}

describe("useRegression", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 显式恢复默认实现：clearAllMocks 后工厂实现可能被全局配置重置
    vi.mocked(listRegressionCases).mockResolvedValue({ total: 0, cases: [] });
    vi.mocked(listRegressionRuns).mockResolvedValue({
      total: 0,
      runs: [],
      offset: 0,
      limit: 50,
    });
    vi.mocked(getRegressionBaseline).mockResolvedValue({ baselineRunId: null });
    error.value = "";
    message.value = "";
  });

  it("选择项目后加载用例/批次/基线", async () => {
    const store = makeStore();
    await vi.waitFor(() => {
      expect(store.selectedProjectId.value).toBe("proj-1");
      expect(getRegressionBaseline).toHaveBeenCalledWith("proj-1");
    });
  });

  it("saveCase 校验名称/goal 为空时不发起请求", async () => {
    const store = makeStore();
    await vi.waitFor(() => expect(store.casesLoading.value).toBe(false));

    store.caseForm.value.name = "用例A";
    store.caseForm.value.goal = "   ";
    const okEmptyGoal = await store.saveCase();
    expect(okEmptyGoal).toBe(false);
    expect(createRegressionCase).not.toHaveBeenCalled();

    store.caseForm.value.goal = "有效目标";
    error.value = "";
    const ok = await store.saveCase();
    expect(ok).toBe(true);
    expect(createRegressionCase).toHaveBeenCalledTimes(1);
  });

  it("saveCase 参数 JSON 非法时报错且不请求", async () => {
    const store = makeStore();
    await vi.waitFor(() => expect(store.casesLoading.value).toBe(false));
    store.caseForm.value.name = "用例B";
    store.caseForm.value.goal = "目标";
    store.caseForm.value.parametersText = "{not-json";
    const ok = await store.saveCase();
    expect(ok).toBe(false);
    expect(error.value).toContain("parameters 解析失败");
    expect(createRegressionCase).not.toHaveBeenCalled();
  });

  it("removeCase 调用删除接口并刷新", async () => {
    vi.mocked(deleteRegressionCase).mockResolvedValueOnce(undefined);
    const store = makeStore();
    await store.removeCase({
      caseId: "regcase-1",
      projectId: "proj-1",
      name: "x",
      taskType: "blackbox",
      goal: "g",
      startUrl: null,
      maxSteps: 5,
      timeoutSeconds: 60,
      captureScreenshots: true,
      parameters: {},
      whiteboxConfigJson: null,
      enabled: true,
      displayOrder: 0,
      createdAt: "",
      updatedAt: "",
    });
    expect(deleteRegressionCase).toHaveBeenCalledWith("regcase-1");
  });

  it("openRunDetail 拉取详情并在终态停止轮询", async () => {
    vi.mocked(getRegressionRun).mockResolvedValue({
      run: {
        runId: "regrun-1",
        projectId: "proj-1",
        triggerSource: "api",
        triggeredBy: null,
        baselineRunId: null,
        status: "completed",
        gateResult: "passed",
        isBaseline: false,
        errorCode: null,
        errorMessage: null,
        startedAt: null,
        completedAt: null,
        createdAt: "",
      },
      items: [],
      summary: {},
    });
    const store = makeStore();
    await store.openRunDetail("regrun-1");
    await vi.waitFor(() => {
      expect(store.detail.value?.run.status).toBe("completed");
      expect(store.detailLoading.value).toBe(false);
    });
    store.closeDetail();
    expect(store.showDetail.value).toBe(false);
    expect(store.detail.value).toBeNull();
  });
});
