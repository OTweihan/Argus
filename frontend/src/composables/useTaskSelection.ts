import { computed, ref, type Ref } from "vue";
import { getTask as apiGetTask, getTaskReportJson as apiGetTaskReportJson } from "../api";
import type { ReportData, Task } from "../types";
import { errorMessage, upsertById } from "../utils";

export type TaskDetailTab = "report" | "timeline" | "llm-debug";

export function useTaskSelection(opts: {
    allTasks: Ref<Task[]>;
    view: Ref<string>;
    error: Ref<string>;
    connectEventStream: () => void;
}) {
    const { allTasks, view, error, connectEventStream } = opts;
    const selectedTaskId = ref<string | null>(null);
    const selectedTaskTab = ref<TaskDetailTab>("report");
    const reportData = ref<ReportData | null>(null);
    const reportLoading = ref(false);

    const selectedTask = computed(() => {
        if (!selectedTaskId.value) return null;
        return allTasks.value.find((task) => task.taskId === selectedTaskId.value) ?? null;
    });

    async function selectTask(taskId: string, tab: TaskDetailTab = "report"): Promise<void> {
        try {
            selectedTaskId.value = taskId;
            selectedTaskTab.value = tab;
            view.value = "task-detail";
            window.location.hash = "task-detail/" + taskId;
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
        selectedTaskTab.value = "report";
        view.value = "tasks";
        history.replaceState(null, "", "#tasks");
    }

    return {
        selectedTaskId,
        selectedTaskTab,
        selectedTask,
        reportData,
        reportLoading,
        selectTask,
        goBackToTasks,
    };
}
