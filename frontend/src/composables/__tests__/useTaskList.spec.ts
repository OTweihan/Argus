/** useTaskList 请求代次 / 取消 / 不可变快照专项测试。
 *
 * 覆盖 O-09 验收：无论请求返回顺序如何，只展示最后一次查询条件对应的数据；
 * loading 准确；已取消请求不产生错误提示或覆盖状态。
 */

import type { Mock } from "vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref, type Ref } from "vue";

import type { Task, TaskListResponse } from "../../types";

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
  return { ApiError, listTasks: vi.fn() };
});

import * as api from "../../api";
import { useTaskList } from "../useTaskList";

const apiListTasksMock = api.listTasks as unknown as Mock<
  [query: Record<string, unknown>, options?: { signal?: AbortSignal }],
  Promise<TaskListResponse>
>;
const ApiErrorClass = api.ApiError as unknown as typeof Error & {
  new (message: string, status: number, code?: string, details?: Record<string, unknown>): Error;
};

function abortError(): Error {
  return new ApiErrorClass("请求已取消。", 0, "REQUEST_ABORTED", { path: "/tasks" });
}

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    taskId: "t1",
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
    reportPath: null,
    resultSummary: null,
    errorMessage: null,
    createdAt: "2026-05-15T00:00:00Z",
    startedAt: null,
    completedAt: null,
    schedulerStatus: null,
    ...overrides,
  } as Task;
}

/** 构造 TaskListResponse：Task 的 findingCount 为可选，运行时与
 * TaskSummaryResponse 同形，这里做一次类型断言即可。 */
function listOf(total: number, ...tasks: Task[]): TaskListResponse {
  return { tasks: tasks as unknown as TaskListResponse["tasks"], total };
}

/** 让 apiListTasks 每次都挂起，并把每个请求的 resolve/reject/signal 记录下来；
 * 同时监听 abort —— 与真实 client 行为一致，取消后立即以 REQUEST_ABORTED 拒绝。 */
interface DeferredEntry {
  signal?: AbortSignal;
  resolve: (value: TaskListResponse) => void;
  reject: (reason: unknown) => void;
}

function makeDeferredListMock(): DeferredEntry[] {
  const entries: DeferredEntry[] = [];
  apiListTasksMock.mockImplementation((_query, options) => {
    const entry: DeferredEntry = {
      signal: options?.signal,
      resolve: () => {},
      reject: () => {},
    };
    const promise = new Promise<TaskListResponse>((res, rej) => {
      entry.resolve = res;
      entry.reject = rej;
      options?.signal?.addEventListener("abort", () => rej(abortError()), { once: true });
    });
    entries.push(entry);
    return promise;
  });
  return entries;
}

interface Harness {
  allTasks: Ref<Task[]>;
  list: ReturnType<typeof useTaskList>;
  onError: Mock<[string], void>;
  dispose: () => void;
}

function setupHarness(): Harness {
  const allTasks = ref<Task[]>([]);
  const onError: Mock<[string], void> = vi.fn();
  const scope = effectScope();
  let list!: ReturnType<typeof useTaskList>;
  scope.run(() => {
    list = useTaskList({ allTasks, onError });
  });
  return { allTasks, list, onError, dispose: () => scope.stop() };
}

async function flushPromises(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe("useTaskList — 请求代次 / 取消 / 快照", () => {
  afterEach(() => {
    vi.clearAllTimers();
  });

  it("加载成功写入 allTasks/total 并复位 loading", async () => {
    const h = setupHarness();
    apiListTasksMock.mockResolvedValue(listOf(1, makeTask({ taskId: "t1" })));

    await h.list.loadTasks();

    expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t1"]);
    expect(h.list.total.value).toBe(1);
    expect(h.list.taskLoading.value).toBe(false);
    expect(apiListTasksMock).toHaveBeenCalledTimes(1);
    expect(h.onError).not.toHaveBeenCalled();
    h.dispose();
  });

  it("旧请求迟到完成不覆盖新条件结果（反序完成）", async () => {
    const h = setupHarness();
    const entries = makeDeferredListMock();

    // 第一次查询（页码 1）挂起
    const p1 = h.list.loadTasks();
    await flushPromises();
    expect(apiListTasksMock).toHaveBeenCalledTimes(1);

    // 快速切页到 2：新请求先返回
    h.list.onPageChange(2);
    await flushPromises();
    expect(entries[1].signal?.aborted).toBe(false);
    entries[1].resolve(listOf(2, makeTask({ taskId: "t2" })));
    await flushPromises();
    expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t2"]);
    expect(h.list.total.value).toBe(2);
    expect(h.list.taskLoading.value).toBe(false);

    // 第一次迟到返回：代次已落后，应被丢弃
    entries[0].resolve(listOf(1, makeTask({ taskId: "t1" })));
    await p1;
    await flushPromises();
    expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t2"]);
    expect(h.list.total.value).toBe(2);
    expect(h.list.taskLoading.value).toBe(false);
    h.dispose();
  });

  it("快速切页：新请求取消旧请求，loading 由最新请求控制", async () => {
    const h = setupHarness();
    const entries = makeDeferredListMock();

    h.list.onPageChange(1);
    await flushPromises();
    expect(h.list.taskLoading.value).toBe(true);
    expect(entries[0].signal?.aborted).toBe(false);

    h.list.onPageChange(2);
    await flushPromises();
    // 旧请求被取消，新请求仍在进行 → loading 保持 true
    expect(entries[0].signal?.aborted).toBe(true);
    expect(h.list.taskLoading.value).toBe(true);

    entries[1].resolve(listOf(1, makeTask({ taskId: "t2" })));
    await flushPromises();
    expect(h.list.taskLoading.value).toBe(false);
    expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t2"]);
    expect(h.onError).not.toHaveBeenCalled();
    h.dispose();
  });

  it("快速筛选：最后一次筛选条件生效，旧结果被丢弃", async () => {
    const h = setupHarness();
    const entries = makeDeferredListMock();

    h.list.taskStatusFilter.value = "running";
    await nextTick();
    await flushPromises();
    expect(apiListTasksMock).toHaveBeenCalledTimes(1);
    expect(apiListTasksMock.mock.calls[0][0].status).toBe("running");

    h.list.taskStatusFilter.value = "failed";
    await nextTick();
    await flushPromises();
    expect(apiListTasksMock).toHaveBeenCalledTimes(2);
    expect(apiListTasksMock.mock.calls[1][0].status).toBe("failed");

    entries[1].resolve(listOf(1, makeTask({ taskId: "t2" })));
    await flushPromises();
    expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t2"]);

    // 旧筛选结果迟到返回：应被丢弃
    entries[0].resolve(listOf(1, makeTask({ taskId: "t1" })));
    await flushPromises();
    expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t2"]);
    expect(h.list.page.value).toBe(1);
    h.dispose();
  });

  it("组件卸载：in-flight 请求被取消且不写状态、不上报错误", async () => {
    const h = setupHarness();
    const entries = makeDeferredListMock();

    const p = h.list.loadTasks();
    await flushPromises();
    expect(h.list.taskLoading.value).toBe(true);
    const signal = entries[0].signal;
    expect(signal?.aborted).toBe(false);

    h.dispose();
    await flushPromises();
    expect(signal?.aborted).toBe(true);
    expect(h.onError).not.toHaveBeenCalled();
    expect(h.allTasks.value).toEqual([]);
    await p; // 被取消的请求静默结束，不应 reject
  });

  it("组件卸载：迟到的成功响应不写状态（disposed 守卫）", async () => {
    const h = setupHarness();
    // 该 mock 不监听 abort：模拟 fetch 已返回、响应微任务在卸载后才落地
    let resolveLate!: (value: TaskListResponse) => void;
    apiListTasksMock.mockImplementationOnce(
      () =>
        new Promise<TaskListResponse>((res) => {
          resolveLate = res;
        }),
    );

    h.list.loadTasks();
    await flushPromises();
    h.dispose();
    resolveLate(listOf(1, makeTask({ taskId: "t1" })));
    await flushPromises();

    expect(h.allTasks.value).toEqual([]);
    expect(h.list.total.value).toBe(0);
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("请求失败：内部触发路径上报 onError 且复位 loading、不污染列表", async () => {
    const h = setupHarness();
    apiListTasksMock.mockRejectedValue(new ApiErrorClass("请求失败：HTTP 500", 500));

    h.list.onPageChange(1);
    await flushPromises();

    expect(h.onError).toHaveBeenCalledTimes(1);
    expect(h.onError).toHaveBeenCalledWith("请求失败：HTTP 500");
    expect(h.list.taskLoading.value).toBe(false);
    expect(h.allTasks.value).toEqual([]);
    h.dispose();
  });

  it("请求失败：显式调用方可 catch 到 rejection", async () => {
    const h = setupHarness();
    apiListTasksMock.mockRejectedValue(new ApiErrorClass("请求失败：HTTP 500", 500));

    await expect(h.list.loadTasks()).rejects.toThrow("请求失败：HTTP 500");
    expect(h.list.taskLoading.value).toBe(false);
    expect(h.onError).not.toHaveBeenCalled();
    h.dispose();
  });

  it("主动取消（当前代次）不视为错误", async () => {
    const h = setupHarness();
    let rejectWithAbort!: (reason: unknown) => void;
    apiListTasksMock.mockImplementationOnce(
      () =>
        new Promise<TaskListResponse>((_, rej) => {
          rejectWithAbort = rej;
        }),
    );

    h.list.onPageChange(1);
    await flushPromises();
    // client.request 把 AbortError 转成 code=REQUEST_ABORTED 的 ApiError
    rejectWithAbort(abortError());
    await flushPromises();

    expect(h.onError).not.toHaveBeenCalled();
    expect(h.list.taskLoading.value).toBe(false);
    expect(h.allTasks.value).toEqual([]);
    h.dispose();
  });

  it("旧请求被取消：不报错、不影响新请求结果", async () => {
    const h = setupHarness();
    const entries = makeDeferredListMock();

    h.list.onPageChange(1);
    await flushPromises();
    h.list.onPageChange(2);
    await flushPromises();
    entries[1].resolve(listOf(1, makeTask({ taskId: "t2" })));
    await flushPromises();

    expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t2"]);
    expect(h.onError).not.toHaveBeenCalled();
    h.dispose();
  });

  it("查询参数为发起时刻的不可变快照，请求期间 ref 变化不影响在途请求", async () => {
    const h = setupHarness();
    const entries = makeDeferredListMock();

    h.list.page.value = 2;
    h.list.pageSize.value = 50;
    const p = h.list.loadTasks();
    await flushPromises();
    expect(apiListTasksMock.mock.calls[0][0].offset).toBe(50);
    expect(apiListTasksMock.mock.calls[0][0].limit).toBe(50);

    // 请求期间修改 page/pageSize 不应影响在途请求的参数
    h.list.page.value = 5;
    h.list.pageSize.value = 10;
    entries[0].resolve(listOf(100, makeTask({ taskId: "t1" })));
    await p;
    await flushPromises();

    expect(apiListTasksMock.mock.calls[0][0].offset).toBe(50);
    expect(apiListTasksMock.mock.calls[0][0].limit).toBe(50);
    expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t1"]);
    h.dispose();
  });
});
