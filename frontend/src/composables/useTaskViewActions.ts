import { ref, type Ref } from "vue";

import { getTask, openAuthenticatedResource, reportPath } from "../api";
import type { Task } from "../types";
import { errorMessage, isAbortError } from "../utils";

export function useTaskViewActions(options: {
  allTasks: Ref<Task[]>;
  selectedTask: Ref<Task | null>;
  error: Ref<string>;
}) {
  const detailVisible = ref(false);
  const detailLoading = ref(false);
  const detailTask = ref<Task | null>(null);

  // 代次守卫：快速先后点开两个任务时，仅最新一次点击允许写入
  // detailTask/detailLoading（与 selectTask 同一口径），防止慢响应串数据。
  let detailSeq = 0;
  let detailAbort: AbortController | null = null;

  async function showTaskDetail(taskId: string): Promise<void> {
    const seq = ++detailSeq;
    detailAbort?.abort();
    const controller = new AbortController();
    detailAbort = controller;

    detailVisible.value = true;
    detailLoading.value = true;
    const cached = options.allTasks.value.find((task) => task.taskId === taskId) ?? null;
    detailTask.value = cached;
    try {
      const fresh = await getTask(taskId, { signal: controller.signal });
      if (seq !== detailSeq) return;
      detailTask.value = fresh;
    } catch (caught) {
      if (seq !== detailSeq || isAbortError(caught)) return;
      options.error.value = errorMessage(caught);
      if (!cached) detailVisible.value = false;
    } finally {
      if (seq === detailSeq) detailLoading.value = false;
    }
  }

  async function openHtmlReport(): Promise<void> {
    if (!options.selectedTask.value) return;
    await runResource(() =>
      openAuthenticatedResource(reportPath(options.selectedTask.value!.taskId)),
    );
  }

  async function downloadHtmlReport(): Promise<void> {
    if (!options.selectedTask.value) return;
    const taskId = options.selectedTask.value.taskId;
    await runResource(() =>
      openAuthenticatedResource(reportPath(taskId, false, true), `argus-report-${taskId}.html`),
    );
  }

  async function downloadJsonReport(): Promise<void> {
    if (!options.selectedTask.value) return;
    const taskId = options.selectedTask.value.taskId;
    await runResource(() =>
      openAuthenticatedResource(reportPath(taskId, true, true), `argus-report-${taskId}.json`),
    );
  }

  async function runResource(operation: () => Promise<void>): Promise<void> {
    try {
      await operation();
    } catch (caught) {
      options.error.value = errorMessage(caught);
    }
  }

  return {
    detailVisible,
    detailLoading,
    detailTask,
    showTaskDetail,
    openHtmlReport,
    downloadHtmlReport,
    downloadJsonReport,
  };
}
