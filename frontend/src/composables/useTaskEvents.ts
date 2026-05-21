import type { Ref } from "vue";

import { getTask as apiGetTask } from "../api";
import type { Task, TaskEvent } from "../types";
import { errorMessage, upsertById } from "../utils";
import { useDebounceFn } from "./useDebounceFn";

/**
 * 运行时事件合并 + 兜底刷新。
 *
 * 原实现里 `applyEvent` 在以下分支统统走 `scheduleRefresh()` 整表 refetch：
 *   - 事件无 `taskId`
 *   - 任务不在当前页 / 当前过滤范围（`idx === -1` 且非 `task.created`）
 *   - 事件 taskId 已知但缺失 `summary`
 *
 * 整表 refetch 是高成本动作：拉一次完整分页 + summary + dashboard。
 * 高频事件下会造成多次重复请求与 UI 抖动。
 *
 * 本版本把 fallback 分成三档，按代价递增：
 *   1. **`scheduleStatsRefresh`**（350 ms 防抖）—— 仅刷 dashboard stats，
 *      用于"任务不在当前页"或"任务被创建/删除/关键状态变化"等改变全量计数
 *      但不会让当前可见列表行结构改变的事件。
 *   2. **`refreshTaskById`** —— 已知具体 taskId 但事件无 task summary 时
 *      只拉这一条任务并 upsert；同 taskId 并发去重。
 *   3. **`scheduleRefresh`**（1000 ms 防抖）—— 真整表 refetch，只用于
 *      "无 taskId 的广播事件"等无法定位变更范围的情况。
 *
 * 这样 90%+ 高频运行时事件不再触发整表 refetch，只更新 dashboard 计数。
 */
export function useTaskEvents(
  allTasks: Ref<Task[]>,
  loadTasks: () => Promise<void>,
  selectedTaskId: Ref<string | null>,
  onError: (msg: string) => void,
  refreshDashboardStats?: () => Promise<void>,
) {
  /* ── 兜底刷新（事件合并失败时 fallback） ── */

  /** 全量兜底：拉分页列表 + summary + dashboard。代价最高。 */
  async function refreshRuntimeData(): Promise<void> {
    try {
      // 仪表盘指标走独立 stats 接口，避免与分页 allTasks 共算。stats 刷新失败
      // 不应阻断列表更新，所以容错落到 onError 而非 throw。
      await Promise.all([
        loadTasks(),
        refreshDashboardStats ? refreshDashboardStats() : Promise.resolve(),
      ]);
      if (selectedTaskId.value) {
        const snapshot = await apiGetTask(selectedTaskId.value);
        if (snapshot) allTasks.value = upsertById(allTasks.value, snapshot, "taskId");
      }
    } catch (caught) {
      onError(errorMessage(caught));
    }
  }

  /** 仅刷 dashboard stats：列表行结构不动，只对齐汇总计数。 */
  async function refreshStatsOnly(): Promise<void> {
    if (!refreshDashboardStats) return;
    try {
      await refreshDashboardStats();
    } catch (caught) {
      onError(errorMessage(caught));
    }
  }

  /** 单条任务拉取并 upsert；同 taskId 并发去重。 */
  const inflightTaskIds = new Set<string>();
  async function refreshTaskById(taskId: string): Promise<void> {
    if (inflightTaskIds.has(taskId)) return;
    inflightTaskIds.add(taskId);
    try {
      const snapshot = await apiGetTask(taskId);
      if (snapshot) allTasks.value = upsertById(allTasks.value, snapshot, "taskId");
    } catch (caught) {
      onError(errorMessage(caught));
    } finally {
      inflightTaskIds.delete(taskId);
    }
  }

  // 整表 refetch 延长到 1000 ms 防抖：fallback 走整表的场景已经被收紧到
  // "无 taskId 广播"这种少数路径，再叠加更激进合并降低尾部压力。
  const scheduleRefresh = useDebounceFn(() => {
    void refreshRuntimeData();
  }, 1000);

  // dashboard stats 刷新 350 ms 防抖：高频任务事件期间合并多次 stats 调用。
  const scheduleStatsRefresh = useDebounceFn(() => {
    void refreshStatsOnly();
  }, 350);

  /* ── 运行时事件合并 ── */

  /** 这些状态变化会让 dashboard 汇总计数（running/finding 等）发生变化。 */
  const STATS_AFFECTING_STATUSES = new Set<Task["status"]>([
    "running",
    "completed",
    "failed",
    "cancelled",
    "timeout",
  ]);

  function applyEvent(event: TaskEvent): void {
    const data = event.data ?? {};
    const eventSummary = data.task as Record<string, unknown> | undefined;
    const taskId =
      (eventSummary?.taskId as string | undefined) ??
      (data.taskId as string | undefined);
    if (!taskId) {
      // 广播事件（无 taskId），可能是配置变更/批量回放等无法定位变更范围的
      // 情况，唯一安全方式仍是整表对齐。
      scheduleRefresh();
      return;
    }

    if (event.eventType === "task.deleted") {
      const idx = allTasks.value.findIndex((t) => t.taskId === taskId);
      if (idx !== -1) {
        allTasks.value.splice(idx, 1);
      }
      // 删除会改变 total / dashboard 计数；列表行结构已本地处理。
      scheduleStatsRefresh();
      return;
    }

    const idx = allTasks.value.findIndex((t) => t.taskId === taskId);
    if (idx === -1 && event.eventType === "task.created") {
      // 拉完整任务对象而非强转事件载荷，避免字段缺失导致运行时错误。
      void refreshTaskById(taskId);
      scheduleStatsRefresh();
      return;
    }

    if (idx === -1) {
      // 任务不在当前页或被过滤排除。整表 refetch 既不会让它出现在当前页
      // （分页 / 过滤条件不变），又浪费带宽 —— 只需对齐 dashboard 计数。
      scheduleStatsRefresh();
      return;
    }

    if (!eventSummary) {
      // 事件带 taskId 但缺少 task summary（如简单 step / progress 事件）：
      // 单点拉这一条任务即可，不需整表 refetch。
      void refreshTaskById(taskId);
      return;
    }

    const existing = allTasks.value[idx];
    const patch: Partial<Task> = {};
    if (eventSummary.status !== undefined) patch.status = eventSummary.status as Task["status"];
    if (eventSummary.currentStep !== undefined) patch.currentStep = eventSummary.currentStep as number;
    if (eventSummary.findingCount !== undefined) patch.findingCount = eventSummary.findingCount as number;
    if (eventSummary.name !== undefined) patch.name = eventSummary.name as string | null;
    if (eventSummary.goal !== undefined) patch.goal = eventSummary.goal as string;
    if (eventSummary.projectId !== undefined) patch.projectId = eventSummary.projectId as string | null;
    if (eventSummary.reportPath !== undefined) patch.reportPath = eventSummary.reportPath as string | null;
    if (eventSummary.resultSummary !== undefined) patch.resultSummary = eventSummary.resultSummary as string | null;
    if (eventSummary.errorMessage !== undefined) patch.errorMessage = eventSummary.errorMessage as string | null;

    if (event.eventType === "task.complete") {
      if (data.reportPath) patch.reportPath = data.reportPath as string;
      if (data.resultSummary) patch.resultSummary = data.resultSummary as string;
    }

    allTasks.value[idx] = { ...existing, ...patch };

    // 关键变更（状态翻转 / finding 数变化）会影响 dashboard：触发轻量刷新。
    const statusChanged =
      patch.status !== undefined &&
      patch.status !== existing.status &&
      STATS_AFFECTING_STATUSES.has(patch.status);
    const findingChanged =
      patch.findingCount !== undefined && patch.findingCount !== existing.findingCount;
    if (statusChanged || findingChanged) {
      scheduleStatsRefresh();
    }
  }

  return {
    applyEvent,
    // 暴露便于上层手动触发兜底（如 WebSocket 重连恢复后补单）；
    // 当前 useConsoleApp 未使用，保留作为扩展点。
    scheduleRefresh,
    scheduleStatsRefresh,
    refreshTaskById,
  };
}
