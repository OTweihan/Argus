import { computed, ref, type Ref } from "vue";

import { getDashboardStats as apiDashboardStats } from "../api";
import type { DashboardStats } from "../types";
import { errorMessage } from "../utils";

/**
 * 仪表盘汇总统计。
 *
 * P1-13：从 `useConsoleApp` 中抽出 dashboard 相关的 ref / loader / computed，
 * 让 useConsoleApp 编排层更聚焦。stats 通过独立的 `/tasks/stats` 接口拉取，
 * 与分页 `allTasks` 解耦，避免被分页范围误导。
 *
 * 使用方在 `loadAll()` 中并发调用 `loadDashboardStats()`；运行时事件期间由
 * `useTaskEvents.scheduleStatsRefresh()` 增量刷新。
 *
 * @param opts.error 共享的错误 ref，stats 加载失败时写入并由顶层 ElMessage 弹出。
 */
export function useDashboardStats(opts: { error: Ref<string> }) {
    const { error } = opts;
    const dashboardStats = ref<DashboardStats | null>(null);

    async function loadDashboardStats(): Promise<void> {
        try {
            dashboardStats.value = await apiDashboardStats(8);
        } catch (caught) {
            error.value = errorMessage(caught);
        }
    }

    // stats 还未加载时回退为 0 / 空数组，DashboardView 显示骨架值。
    const tasksTotal = computed(() => dashboardStats.value?.tasksTotal ?? 0);
    const runningCount = computed(() => dashboardStats.value?.runningTotal ?? 0);
    const findingCount = computed(() => dashboardStats.value?.findingsTotal ?? 0);
    const recentTasks = computed(() => dashboardStats.value?.recentTasks ?? []);

    return {
        dashboardStats,
        loadDashboardStats,
        tasksTotal,
        runningCount,
        findingCount,
        recentTasks,
    };
}
