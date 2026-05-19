import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import type { DashboardStats } from "../../types";

// 模块级 mock：避免真实 HTTP 调用。
// 必须用 importOriginal 保留 ApiError 类（utils.errorMessage 会 instanceof 它），
// 否则会报 "Right-hand side of instanceof is not callable"。
vi.mock("../../api", async (importOriginal) => {
    const actual = (await importOriginal()) as Record<string, unknown>;
    return {
        ...actual,
        getDashboardStats: vi.fn(),
    };
});

import * as apiModule from "../../api";
import { useDashboardStats } from "../useDashboardStats";

const apiMock = apiModule.getDashboardStats as unknown as ReturnType<typeof vi.fn>;

function makeStats(overrides: Partial<DashboardStats> = {}): DashboardStats {
    return {
        tasksTotal: 0,
        runningTotal: 0,
        findingsTotal: 0,
        recentTasks: [],
        ...overrides,
    } as DashboardStats;
}

describe("useDashboardStats", () => {
    beforeEach(() => {
        apiMock.mockReset();
    });

    afterEach(() => {
        apiMock.mockReset();
    });

    it("初始状态：dashboardStats 为 null，computed 返回安全默认值", () => {
        const error = ref("");
        const ds = useDashboardStats({ error });

        expect(ds.dashboardStats.value).toBeNull();
        expect(ds.tasksTotal.value).toBe(0);
        expect(ds.runningCount.value).toBe(0);
        expect(ds.findingCount.value).toBe(0);
        expect(ds.recentTasks.value).toEqual([]);
    });

    it("loadDashboardStats 成功：stats 更新，computed 反映新值", async () => {
        const error = ref("");
        apiMock.mockResolvedValue(
            makeStats({ tasksTotal: 42, runningTotal: 3, findingsTotal: 7 }),
        );

        const ds = useDashboardStats({ error });
        await ds.loadDashboardStats();

        expect(apiMock).toHaveBeenCalledWith(8);
        expect(ds.dashboardStats.value?.tasksTotal).toBe(42);
        expect(ds.tasksTotal.value).toBe(42);
        expect(ds.runningCount.value).toBe(3);
        expect(ds.findingCount.value).toBe(7);
        expect(error.value).toBe("");
    });

    it("loadDashboardStats 失败：错误写入 error ref，stats 保留旧值", async () => {
        const error = ref("");
        // 先成功加载一次，建立"旧值"
        apiMock.mockResolvedValueOnce(makeStats({ tasksTotal: 10 }));
        const ds = useDashboardStats({ error });
        await ds.loadDashboardStats();
        expect(ds.tasksTotal.value).toBe(10);

        // 第二次失败
        apiMock.mockRejectedValueOnce(new Error("502 Bad Gateway"));
        await ds.loadDashboardStats();
        expect(error.value).toBe("502 Bad Gateway");
        // 旧值未被清空
        expect(ds.tasksTotal.value).toBe(10);
    });

    it("recentTasks computed：返回 API 给的最近任务列表副本", async () => {
        const error = ref("");
        const recent: DashboardStats["recentTasks"] = [
            { taskId: "t1", goal: "demo1" } as NonNullable<DashboardStats["recentTasks"]>[number],
            { taskId: "t2", goal: "demo2" } as NonNullable<DashboardStats["recentTasks"]>[number],
        ];
        apiMock.mockResolvedValue(makeStats({ recentTasks: recent }));

        const ds = useDashboardStats({ error });
        await ds.loadDashboardStats();

        expect(ds.recentTasks.value).toHaveLength(2);
        expect(ds.recentTasks.value[0]?.taskId).toBe("t1");
    });
});
