import type { Mock } from "vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, ref, type Ref } from "vue";

import type { Task, TaskEvent } from "../../types";

// 对 ../api 做模块级 mock：保证 useTaskEvents 内部的 apiGetTask
// 走可控的 mock 实现，测试不依赖真实 HTTP 调用。
vi.mock("../../api", () => ({
    getTask: vi.fn(),
}));

import * as apiModule from "../../api";
import { useTaskEvents } from "../useTaskEvents";

const apiGetTaskMock = apiModule.getTask as unknown as ReturnType<typeof vi.fn>;

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

interface Harness {
    allTasks: Ref<Task[]>;
    selectedTaskId: Ref<string | null>;
    loadTasks: Mock<[], Promise<void>>;
    refreshStats: Mock<[], Promise<void>>;
    onError: Mock<[string], void>;
    events: ReturnType<typeof useTaskEvents>;
    dispose: () => void;
}

function setupHarness(initialTasks: Task[] = []): Harness {
    const allTasks = ref<Task[]>(initialTasks);
    const selectedTaskId = ref<string | null>(null);
    const loadTasks: Mock<[], Promise<void>> = vi.fn(() => Promise.resolve());
    const refreshStats: Mock<[], Promise<void>> = vi.fn(() => Promise.resolve());
    const onError: Mock<[string], void> = vi.fn();

    // 在 effectScope 里运行 useTaskEvents 以便 useDebounceFn 注册的
    // onScopeDispose 回调可被 stop() 触发，避免测试间相互污染。
    const scope = effectScope();
    let events!: ReturnType<typeof useTaskEvents>;
    scope.run(() => {
        events = useTaskEvents(
            allTasks,
            loadTasks,
            selectedTaskId,
            onError,
            refreshStats,
        );
    });

    return {
        allTasks,
        selectedTaskId,
        loadTasks,
        refreshStats,
        onError,
        events,
        dispose: () => scope.stop(),
    };
}

// 让 setTimeout 走 fake；async 任务通过 vi.runAllTimersAsync + flushPromises 推进。
async function flushPromises(): Promise<void> {
    // 三层 microtask 足够覆盖：refreshTaskById → upsert / refreshStats → debounce 内部 await。
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
}

describe("useTaskEvents.applyEvent — fallback 路径收紧", () => {
    beforeEach(() => {
        vi.useFakeTimers();
        apiGetTaskMock.mockReset();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("无 taskId 的广播事件触发整表 refetch（scheduleRefresh, 1000ms）", async () => {
        const h = setupHarness([makeTask({ taskId: "t1" })]);

        h.events.applyEvent({ eventType: "task.broadcast", data: {} } as TaskEvent);

        // 立即不应触发
        expect(h.loadTasks).not.toHaveBeenCalled();
        expect(h.refreshStats).not.toHaveBeenCalled();

        // 999ms 之前也不应触发
        await vi.advanceTimersByTimeAsync(999);
        expect(h.loadTasks).not.toHaveBeenCalled();

        // 满 1000ms 触发整表 refetch
        await vi.advanceTimersByTimeAsync(1);
        await flushPromises();
        expect(h.loadTasks).toHaveBeenCalledTimes(1);
        expect(h.refreshStats).toHaveBeenCalledTimes(1);

        h.dispose();
    });

    it("task.deleted 命中本地：剔除该行 + 仅 stats 刷新（不重拉整表）", async () => {
        const h = setupHarness([
            makeTask({ taskId: "t1" }),
            makeTask({ taskId: "t2" }),
        ]);

        h.events.applyEvent({
            eventType: "task.deleted",
            data: { taskId: "t1" },
        } as TaskEvent);

        expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t2"]);

        await vi.advanceTimersByTimeAsync(350);
        await flushPromises();
        expect(h.refreshStats).toHaveBeenCalledTimes(1);
        expect(h.loadTasks).not.toHaveBeenCalled();

        h.dispose();
    });

    it("task.created 且不在当前页：走 refreshTaskById 拉完整对象 + stats 刷新", async () => {
        const h = setupHarness([makeTask({ taskId: "t1" })]);
        const newTaskSummary = { taskId: "t2", status: "pending", goal: "new" };
        apiGetTaskMock.mockResolvedValue(
            makeTask({ taskId: "t2", status: "pending", goal: "new" }),
        );

        h.events.applyEvent({
            eventType: "task.created",
            data: { task: newTaskSummary },
        } as TaskEvent);

        // 不强制转载荷，列表不动（refreshTaskById resolve 后才 upsert）
        expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t1"]);

        await flushPromises();
        await flushPromises();
        expect(apiGetTaskMock).toHaveBeenCalledTimes(1);
        expect(apiGetTaskMock).toHaveBeenCalledWith("t2");
        expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t2", "t1"]);

        await vi.advanceTimersByTimeAsync(350);
        await flushPromises();
        expect(h.refreshStats).toHaveBeenCalledTimes(1);
        expect(h.loadTasks).not.toHaveBeenCalled();

        h.dispose();
    });

    it("事件 taskId 不在当前页 + 非 created：仅 stats 刷新，不重拉整表", async () => {
        const h = setupHarness([makeTask({ taskId: "t1" })]);

        h.events.applyEvent({
            eventType: "task.updated",
            data: { taskId: "t-out-of-page", task: { taskId: "t-out-of-page" } },
        } as TaskEvent);

        // 列表不动
        expect(h.allTasks.value.map((t) => t.taskId)).toEqual(["t1"]);

        await vi.advanceTimersByTimeAsync(350);
        await flushPromises();
        expect(h.refreshStats).toHaveBeenCalledTimes(1);
        expect(h.loadTasks).not.toHaveBeenCalled();
        expect(apiGetTaskMock).not.toHaveBeenCalled();

        h.dispose();
    });

    it("事件 taskId 已知但缺失 summary：单点拉取该任务，不重拉整表", async () => {
        const h = setupHarness([makeTask({ taskId: "t1", status: "running" })]);
        apiGetTaskMock.mockResolvedValue(
            makeTask({ taskId: "t1", status: "completed", findingCount: 2 }),
        );

        h.events.applyEvent({
            eventType: "task.progress",
            data: { taskId: "t1" },
        } as TaskEvent);

        // refreshTaskById 是 async；推进 microtask 让 fetch 完成。
        await flushPromises();
        await flushPromises();

        expect(apiGetTaskMock).toHaveBeenCalledTimes(1);
        expect(apiGetTaskMock).toHaveBeenCalledWith("t1");
        // upsert 把 t1 替换为新快照
        expect(h.allTasks.value[0]?.status).toBe("completed");
        expect(h.allTasks.value[0]?.findingCount).toBe(2);
        // 单点路径不应触发整表 refetch
        expect(h.loadTasks).not.toHaveBeenCalled();

        h.dispose();
    });

    it("同 taskId 并发 refreshTaskById：第二次去重，apiGetTask 只调一次", async () => {
        const h = setupHarness([makeTask({ taskId: "t1" })]);
        // 让第一次拉取 pending，直到我们手动 resolve。
        let resolveFirst: (value: Task) => void = () => {};
        apiGetTaskMock.mockImplementationOnce(
            () => new Promise<Task>((res) => { resolveFirst = res; }),
        );

        h.events.applyEvent({ eventType: "task.progress", data: { taskId: "t1" } } as TaskEvent);
        h.events.applyEvent({ eventType: "task.progress", data: { taskId: "t1" } } as TaskEvent);

        await flushPromises();
        expect(apiGetTaskMock).toHaveBeenCalledTimes(1);

        resolveFirst(makeTask({ taskId: "t1", status: "running" }));
        await flushPromises();
        h.dispose();
    });

    it("增量合并：状态翻转到 completed 触发 stats 刷新", async () => {
        const h = setupHarness([makeTask({ taskId: "t1", status: "running" })]);

        h.events.applyEvent({
            eventType: "task.complete",
            data: {
                taskId: "t1",
                task: { taskId: "t1", status: "completed" },
                reportPath: "/some/report.html",
            },
        } as TaskEvent);

        expect(h.allTasks.value[0]?.status).toBe("completed");
        expect(h.allTasks.value[0]?.reportPath).toBe("/some/report.html");

        await vi.advanceTimersByTimeAsync(350);
        await flushPromises();
        expect(h.refreshStats).toHaveBeenCalledTimes(1);
        expect(h.loadTasks).not.toHaveBeenCalled();

        h.dispose();
    });

    it("增量合并：findingCount 变化触发 stats 刷新", async () => {
        const h = setupHarness([makeTask({ taskId: "t1", status: "running", findingCount: 0 })]);

        h.events.applyEvent({
            eventType: "task.findings",
            data: { taskId: "t1", task: { taskId: "t1", findingCount: 3 } },
        } as TaskEvent);

        expect(h.allTasks.value[0]?.findingCount).toBe(3);

        await vi.advanceTimersByTimeAsync(350);
        await flushPromises();
        expect(h.refreshStats).toHaveBeenCalledTimes(1);
        expect(h.loadTasks).not.toHaveBeenCalled();

        h.dispose();
    });

    it("增量合并：纯元数据变化（goal/name），状态未翻转 → 不触发 stats 刷新", async () => {
        const h = setupHarness([makeTask({ taskId: "t1", status: "running", goal: "old" })]);

        h.events.applyEvent({
            eventType: "task.updated",
            data: { taskId: "t1", task: { taskId: "t1", goal: "new goal" } },
        } as TaskEvent);

        expect(h.allTasks.value[0]?.goal).toBe("new goal");

        await vi.advanceTimersByTimeAsync(1000);
        await flushPromises();
        expect(h.refreshStats).not.toHaveBeenCalled();
        expect(h.loadTasks).not.toHaveBeenCalled();

        h.dispose();
    });

    it("高频事件期间多次 fallback：stats 刷新被合并为 1 次（350ms 防抖）", async () => {
        const h = setupHarness([makeTask({ taskId: "t1" })]);

        for (let i = 0; i < 5; i += 1) {
            h.events.applyEvent({
                eventType: "task.updated",
                data: { taskId: `t-other-${i}`, task: { taskId: `t-other-${i}` } },
            } as TaskEvent);
            await vi.advanceTimersByTimeAsync(50);
        }

        // 总共推进 250ms，未到 350ms，应未触发
        expect(h.refreshStats).not.toHaveBeenCalled();

        await vi.advanceTimersByTimeAsync(350);
        await flushPromises();
        expect(h.refreshStats).toHaveBeenCalledTimes(1);
        expect(h.loadTasks).not.toHaveBeenCalled();

        h.dispose();
    });
});
