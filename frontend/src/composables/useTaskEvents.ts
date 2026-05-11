import { onUnmounted, type Ref } from "vue";

import { getTask as apiGetTask, summary as apiSummary } from "../api";
import type { ConfigSummary, Task, TaskEvent } from "../types";
import { errorMessage, upsertById } from "../utils";

export function useTaskEvents(
  allTasks: Ref<Task[]>,
  loadTasks: () => Promise<void>,
  selectedTaskId: Ref<string | null>,
  onError: (msg: string) => void,
  onSummaryUpdate: (summary: ConfigSummary) => void,
) {
  let refreshTimer: number | null = null;

  onUnmounted(() => {
    if (refreshTimer !== null) window.clearTimeout(refreshTimer);
  });

  /* ── 兜底刷新（事件合并失败时 fallback） ── */

  async function refreshRuntimeData(): Promise<void> {
    try {
      const [summaryResponse] = await Promise.all([
        apiSummary(),
        loadTasks(),
      ]);
      if (selectedTaskId.value) {
        const snapshot = await apiGetTask(selectedTaskId.value);
        if (snapshot) allTasks.value = upsertById(allTasks.value, snapshot, "taskId");
      }
      onSummaryUpdate(summaryResponse);
    } catch (caught) {
      onError(errorMessage(caught));
    }
  }

  function scheduleRefresh(): void {
    if (refreshTimer !== null) window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => {
      refreshTimer = null;
      void refreshRuntimeData();
    }, 350);
  }

  /* ── 运行时事件合并 ── */

  function applyEvent(event: TaskEvent): void {
    const data = event.data ?? {};
    const eventSummary = data.task as Record<string, unknown> | undefined;
    const taskId =
      (eventSummary?.taskId as string | undefined) ??
      (data.taskId as string | undefined);
    if (!taskId) {
      scheduleRefresh();
      return;
    }

    const eventType = event.eventType ?? event.type ?? "";
    if (eventType === "task.deleted") {
      const idx = allTasks.value.findIndex((t) => t.taskId === taskId);
      if (idx !== -1) {
        allTasks.value = [
          ...allTasks.value.slice(0, idx),
          ...allTasks.value.slice(idx + 1),
        ];
      }
      return;
    }

    const idx = allTasks.value.findIndex((t) => t.taskId === taskId);
    if (idx === -1 && eventType === "task.created" && eventSummary) {
      allTasks.value = [eventSummary as unknown as Task, ...allTasks.value];
      return;
    }

    if (idx === -1 || !eventSummary) {
      scheduleRefresh();
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

    if (eventType === "task.complete") {
      patch.status = "completed";
      if (data.reportPath) patch.reportPath = data.reportPath as string;
      if (data.resultSummary) patch.resultSummary = data.resultSummary as string;
    }

    allTasks.value = [
      ...allTasks.value.slice(0, idx),
      { ...existing, ...patch },
      ...allTasks.value.slice(idx + 1),
    ];
  }

  return { applyEvent };
}
