/** useTaskSelection 代次守卫 + 取消 + 浅响应式专项测试。
 *
 * 覆盖 F-M1/F-H3 验收：快速切换任务时旧报告不能渲染到错误任务下，loading 由
 * 最新一次选择驱动；abort 不产生错误提示；报告 payload 只整体替换。
 */

import type { Mock } from "vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref, type Ref } from "vue";

import type { ReportData, ReportTask, Task } from "../../types";

vi.mock("../../api", () => {
  class ApiError extends Error {
    constructor(
      message: string,
      public status: number,
      public code = "HTTP_ERROR",
      public details: Record<string, unknown> = {},
    ) {
      super(message);
    }
  }
  return { ApiError, getTask: vi.fn(), getTaskReportJson: vi.fn() };
});

import * as api from "../../api";
import { useTaskSelection } from "../useTaskSelection";

const apiGetTaskMock = api.getTask as unknown as Mock<
  [taskId: string, options?: { signal?: AbortSignal }],
  Promise<Task>
>;
const apiGetReportJsonMock = api.getTaskReportJson as unknown as Mock<
  [taskId: string, options?: { signal?: AbortSignal }],
  Promise<ReportData>
>;
const ApiErrorClass = api.ApiError as unknown as typeof Error & {
  new (message: string, status: number, code?: string, details?: Record<string, unknown>): Error;
};

function abortError(): Error {
  return new ApiErrorClass("请求已取消。", 0, "REQUEST_ABORTED", {});
}

function makeTask(taskId: string, overrides: Partial<Task> = {}): Task {
  return {
    taskId,
    type: "blackbox",
    projectId: null,
    name: null,
    goal: "demo",
    startUrl: null,
    maxSteps: 10,
    parameters: {},
    status: "pending",
    currentStep: 0,
    findingCount: 0,
    reportPath: `/reports/${taskId}/report.json`,
    resultSummary: null,
    errorMessage: null,
    createdAt: "2026-05-15T00:00:00Z",
    startedAt: null,
    completedAt: null,
    schedulerStatus: null,
    ...overrides,
  } as Task;
}

interface Deferred<T> {
  signal?: AbortSignal;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
}

function makeReportData(taskId: string): ReportData {
  return {
    reportId: `r-${taskId}`,
    task: makeTask(taskId) as ReportTask,
    title: "test report",
    summary: "summary",
    generatedAt: "2026-05-15T00:00:00Z",
    steps: [],
    findings: [],
    displaySteps: [],
    totalStepsCount: 0,
    hiddenStepsCount: 0,
  };
}

/** 让 getTask / getTaskReportJson 每次都挂起并记录 signal；abort 后以 REQUEST_ABORTED 拒绝。 */
function makeDeferredMocks() {
  const taskEntries: Deferred<Task>[] = [];
  const reportEntries: Deferred<ReportData>[] = [];
  apiGetTaskMock.mockImplementation((_taskId, options) => {
    const entry: Deferred<Task> = { signal: options?.signal, resolve: () => {}, reject: () => {} };
    const promise = new Promise<Task>((res, rej) => {
      entry.resolve = res;
      entry.reject = rej;
      options?.signal?.addEventListener("abort", () => rej(abortError()), { once: true });
    });
    taskEntries.push(entry);
    return promise;
  });
  apiGetReportJsonMock.mockImplementation((_taskId, options) => {
    const entry: Deferred<ReportData> = {
      signal: options?.signal,
      resolve: () => {},
      reject: () => {},
    };
    const promise = new Promise<ReportData>((res, rej) => {
      entry.resolve = res;
      entry.reject = rej;
      options?.signal?.addEventListener("abort", () => rej(abortError()), { once: true });
    });
    reportEntries.push(entry);
    return promise;
  });
  return { taskEntries, reportEntries };
}

function setupHarness() {
  const allTasks = ref<Task[]>([]) as Ref<Task[]>;
  const view = ref("");
  const error = ref("");
  const sel = useTaskSelection({ allTasks, view, error });
  return { allTasks, view, error, sel };
}

async function flushPromises(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await nextTick();
}

describe("useTaskSelection — 代次守卫 / 取消 / 浅响应式", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("先选 A 后选 B，只渲染 B；A 被 abort，迟到响应不覆盖", async () => {
    const { allTasks, error, sel } = setupHarness();
    const { taskEntries, reportEntries } = makeDeferredMocks();

    const pA = sel.selectTask("task-a");
    const pB = sel.selectTask("task-b");
    // 第二次选择应立即 abort 第一次请求（task-a 的 getTask 被取消）
    expect(taskEntries[0].signal?.aborted).toBe(true);

    await flushPromises();
    // task-b 返回，随后其 report.json 返回（A 被 abort，从未请求报告 → report 只 1 条）
    taskEntries[1].resolve(makeTask("task-b", { status: "completed" }));
    await flushPromises();
    expect(reportEntries).toHaveLength(1);
    reportEntries[0].resolve(makeReportData("task-b"));
    await pB;
    // A 的 getTask 以 REQUEST_ABORTED 拒绝 → 代次过期，不写状态、不弹错误
    taskEntries[0].reject(abortError());
    await pA.catch(() => undefined);
    await flushPromises();

    expect(sel.selectedTaskId.value).toBe("task-b");
    expect(sel.reportLoading.value).toBe(false);
    expect(sel.reportData.value?.task?.taskId).toBe("task-b");
    expect(error.value).toBe("");
    expect(allTasks.value.map((t) => t.taskId)).toEqual(["task-b"]);
  });

  it("reportLoading 由最新一次选择驱动，旧 finally 不清新 loading", async () => {
    const { sel } = setupHarness();
    const { taskEntries } = makeDeferredMocks();

    const pA = sel.selectTask("task-a");
    const pB = sel.selectTask("task-b");
    await flushPromises();

    // A 的 getTask 被 abort 拒绝 → A 的 finally 因代次过期不清 loading
    taskEntries[0].reject(abortError());
    await pA.catch(() => undefined);
    await flushPromises();

    expect(sel.reportLoading.value).toBe(true); // B 仍在加载

    taskEntries[1].resolve(makeTask("task-b", { reportPath: null }));
    await pB;
    await flushPromises();
    expect(sel.reportLoading.value).toBe(false);
  });

  it("无报告路径的任务不请求 report.json，直接结束加载", async () => {
    const { sel } = setupHarness();
    const { taskEntries, reportEntries } = makeDeferredMocks();

    const p = sel.selectTask("task-c");
    await flushPromises();
    taskEntries[0].resolve(makeTask("task-c", { reportPath: null }));
    await p;
    await flushPromises();

    expect(reportEntries).toHaveLength(0);
    expect(sel.reportData.value).toBeNull();
    expect(sel.reportLoading.value).toBe(false);
  });

  it("真实失败仍写入 error", async () => {
    const { error, sel } = setupHarness();
    const { taskEntries } = makeDeferredMocks();

    const p = sel.selectTask("task-fail");
    await flushPromises();
    taskEntries[0].reject(new ApiErrorClass("boom", 500));
    await p.catch(() => undefined);

    expect(error.value).toContain("boom");
    expect(sel.reportLoading.value).toBe(false);
  });
});
