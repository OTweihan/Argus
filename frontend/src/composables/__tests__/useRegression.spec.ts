import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function runDetail(status: "running" | "completed" = "running") {
  return {
    run: {
      runId: "regrun-poll",
      projectId: "proj-1",
      triggerSource: "api" as const,
      triggeredBy: null,
      baselineRunId: null,
      status,
      gateResult: status === "completed" ? ("passed" as const) : null,
      isBaseline: false,
      errorCode: null,
      errorMessage: null,
      startedAt: null,
      completedAt: null,
      createdAt: "",
    },
    items: [],
    summary: {},
  };
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

  it("快速切换项目时忽略较晚返回的旧项目数据", async () => {
    const oldCases = deferred<Awaited<ReturnType<typeof listRegressionCases>>>();
    vi.mocked(listRegressionCases)
      .mockImplementationOnce(() => oldCases.promise)
      .mockResolvedValueOnce({
        total: 1,
        cases: [
          {
            caseId: "case-new",
            projectId: "proj-2",
            name: "新项目用例",
            taskType: "blackbox",
            goal: "goal",
            startUrl: null,
            maxSteps: 10,
            timeoutSeconds: 60,
            captureScreenshots: true,
            parameters: {},
            whiteboxConfigJson: null,
            enabled: true,
            displayOrder: 0,
            createdAt: "",
            updatedAt: "",
          },
        ],
      });

    const store = makeStore();
    await nextTick();
    expect(listRegressionCases).toHaveBeenCalledWith("proj-1");
    store.selectProject("proj-2");
    await vi.waitFor(() => expect(store.cases.value[0]?.caseId).toBe("case-new"));

    oldCases.resolve({ total: 0, cases: [] });
    await oldCases.promise;
    expect(store.cases.value[0]?.caseId).toBe("case-new");
  });

  it("所有用例停用时不允许发起批次", async () => {
    vi.mocked(listRegressionCases).mockResolvedValueOnce({
      total: 1,
      cases: [
        {
          caseId: "case-disabled",
          projectId: "proj-1",
          name: "停用用例",
          taskType: "blackbox",
          goal: "goal",
          startUrl: null,
          maxSteps: 10,
          timeoutSeconds: 60,
          captureScreenshots: true,
          parameters: {},
          whiteboxConfigJson: null,
          enabled: false,
          displayOrder: 0,
          createdAt: "",
          updatedAt: "",
        },
      ],
    });
    const store = makeStore();
    await vi.waitFor(() => expect(store.cases.value).toHaveLength(1));
    expect(store.selectedProjectHasCases.value).toBe(false);
  });

  it("详情抽屉关闭后忽略尚未完成的详情请求", async () => {
    const pendingDetail = deferred<Awaited<ReturnType<typeof getRegressionRun>>>();
    vi.mocked(getRegressionRun).mockImplementationOnce(() => pendingDetail.promise);
    const store = makeStore();
    const opening = store.openRunDetail("regrun-slow");
    const signal = vi.mocked(getRegressionRun).mock.calls[0]?.[1]?.signal;
    store.closeDetail();

    expect(signal?.aborted).toBe(true);

    pendingDetail.resolve({
      run: {
        runId: "regrun-slow",
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
    await opening;
    expect(store.showDetail.value).toBe(false);
    expect(store.detail.value).toBeNull();
    expect(store.detailLoading.value).toBe(false);
  });

  it("慢轮询完成前不启动重叠请求", async () => {
    vi.useFakeTimers();
    try {
      const pendingPoll = deferred<Awaited<ReturnType<typeof getRegressionRun>>>();
      vi.mocked(getRegressionRun)
        .mockResolvedValueOnce(runDetail())
        .mockImplementationOnce(() => pendingPoll.promise)
        .mockResolvedValue(runDetail());
      const store = makeStore();

      await store.openRunDetail("regrun-poll");
      expect(getRegressionRun).toHaveBeenCalledTimes(1);

      await vi.advanceTimersByTimeAsync(3000);
      expect(getRegressionRun).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(9000);
      expect(getRegressionRun).toHaveBeenCalledTimes(2);

      pendingPoll.resolve(runDetail());
      await pendingPoll.promise;
      await vi.runAllTicks();
      await vi.advanceTimersByTimeAsync(2999);
      expect(getRegressionRun).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(1);
      expect(getRegressionRun).toHaveBeenCalledTimes(3);
      store.closeDetail();
    } finally {
      vi.useRealTimers();
    }
  });

  it("详情进入终态后不再安排轮询", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(getRegressionRun).mockResolvedValue(runDetail("completed"));
      const store = makeStore();

      await store.openRunDetail("regrun-poll");
      await vi.advanceTimersByTimeAsync(12000);

      expect(getRegressionRun).toHaveBeenCalledTimes(1);
      store.closeDetail();
    } finally {
      vi.useRealTimers();
    }
  });
});
