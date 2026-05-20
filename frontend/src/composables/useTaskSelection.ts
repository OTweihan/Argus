import { computed, ref, type Ref } from "vue";
import { getTask as apiGetTask, getTaskReportJson as apiGetTaskReportJson } from "../api";
import type { ReportData, Task } from "../types";
import { errorMessage, upsertById } from "../utils";

export type TaskDetailTab = "report" | "timeline" | "llm-debug";

/**
 * 本 composable 只负责"选中态"这一份纯状态（selectedTaskId / selectedTask /
 * reportData 等），**不再**主动驱动 WebSocket 重连。
 *
 * WS 重连由编排层 `useConsoleApp` 通过 `watch([view, selectedTaskId])` 接管，
 * 避免之前为"useTasks 需要 connectEventStream、connectEventStream 又需要
 * selectedTaskId"的鸡生蛋问题而采用的 holder ref hack。
 */
export function useTaskSelection(opts: {
    allTasks: Ref<Task[]>;
    view: Ref<string>;
    error: Ref<string>;
}) {
    const { allTasks, view, error } = opts;
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
            // 先翻转 view 与 selectedTaskId，使编排层 watch 能在数据加载期间
            // 就已触发 WS 重连，事件接收点更早。
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
