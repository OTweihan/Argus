import { ref, type Ref } from "vue";

import { getTask, openAuthenticatedResource, reportPath } from "../api";
import type { Task } from "../types";
import { errorMessage } from "../utils";

export function useTaskViewActions(options: {
  allTasks: Ref<Task[]>;
  selectedTask: Ref<Task | null>;
  error: Ref<string>;
}) {
  const detailVisible = ref(false);
  const detailLoading = ref(false);
  const detailTask = ref<Task | null>(null);

  async function showTaskDetail(taskId: string): Promise<void> {
    detailVisible.value = true;
    detailLoading.value = true;
    const cached = options.allTasks.value.find((task) => task.taskId === taskId) ?? null;
    detailTask.value = cached;
    try {
      detailTask.value = await getTask(taskId);
    } catch (caught) {
      options.error.value = errorMessage(caught);
      if (!cached) detailVisible.value = false;
    } finally {
      detailLoading.value = false;
    }
  }

  async function openHtmlReport(): Promise<void> {
    if (!options.selectedTask.value) return;
    await runResource(() => openAuthenticatedResource(
      reportPath(options.selectedTask.value!.taskId),
    ));
  }

  async function downloadHtmlReport(): Promise<void> {
    if (!options.selectedTask.value) return;
    const taskId = options.selectedTask.value.taskId;
    await runResource(() => openAuthenticatedResource(
      reportPath(taskId, false, true),
      `argus-report-${taskId}.html`,
    ));
  }

  async function downloadJsonReport(): Promise<void> {
    if (!options.selectedTask.value) return;
    const taskId = options.selectedTask.value.taskId;
    await runResource(() => openAuthenticatedResource(
      reportPath(taskId, true, true),
      `argus-report-${taskId}.json`,
    ));
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
