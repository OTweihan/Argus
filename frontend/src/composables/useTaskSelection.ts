import { computed, ref, type Ref } from "vue";
import { getTask as apiGetTask, getTaskReportJson as apiGetTaskReportJson } from "../api";
import type { ReportData, Task } from "../types";
import { errorMessage, upsertById } from "../utils";

export function useTaskSelection(opts: {
    allTasks: Ref<Task[]>;
    view: Ref<string>;
    error: Ref<string>;
    connectEventStream: () => void;
}) {
    const { allTasks, view, error, connectEventStream } = opts;
    const selectedTaskId = ref<string | null>(null);
    const reportData = ref<ReportData | null>(null);
    const reportLoading = ref(false);

    const selectedTask = computed(() => {
        if (!selectedTaskId.value) return null;
        return allTasks.value.find((task) => task.taskId === selectedTaskId.value) ?? null;
    });

    async function selectTask(taskId: string): Promise<void> {
        try {
            selectedTaskId.value = taskId;
            view.value = "task-detail";
            reportData.value = null;
            reportLoading.value = true;
            const task = await apiGetTask(taskId);
            allTasks.value = upsertById(allTasks.value, task, "taskId");
            if (task.reportPath) {
                const data = await apiGetTaskReportJson(taskId);
                reportData.value = data;
            }
            connectEventStream();
        } catch (caught) {
            error.value = errorMessage(caught);
        } finally {
            reportLoading.value = false;
        }
    }

    function goBackToTasks(): void {
        selectedTaskId.value = null;
        view.value = "tasks";
        connectEventStream();
    }

    return {
        selectedTaskId,
        selectedTask,
        reportData,
        reportLoading,
        selectTask,
        goBackToTasks,
    };
}
