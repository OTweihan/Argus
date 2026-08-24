import { ElMessageBox } from "element-plus";
import type { Ref } from "vue";
import {
  deleteTask as apiDeleteTask,
  restartTask as apiRestartTask,
  startTask as apiStartTask,
} from "../api";
import type { Task } from "../types";
import { errorMessage, overloadMessage, upsertById } from "../utils";

/** 任务生命周期操作：start / retry / delete。
 * 与表单无关，只依赖任务列表与选中态的最小切片。 */
export function useTaskActions(opts: {
  allTasks: Ref<Task[]>;
  error: Ref<string>;
  message: Ref<string>;
  loadTasks: () => Promise<void>;
  total: Ref<number>;
  page: Ref<number>;
  selectedTaskId: Ref<string | null>;
}) {
  const { allTasks, error, message, loadTasks, total, page, selectedTaskId } = opts;

  async function startTask(taskId: string): Promise<void> {
    try {
      const result = await apiStartTask(taskId);
      allTasks.value = upsertById(allTasks.value, result.task, "taskId");
      message.value = `任务已入队：${result.schedulerStatus}`;
      error.value = "";
    } catch (caught) {
      error.value = overloadMessage(caught);
      message.value = "";
    }
  }

  async function retryTask(taskId: string): Promise<void> {
    try {
      await apiRestartTask(taskId);
      await loadTasks();
      message.value = "任务已重新入队。";
      error.value = "";
    } catch (caught) {
      error.value = overloadMessage(caught);
      message.value = "";
    }
  }

  async function deleteTask(task: Task): Promise<void> {
    if (task.status !== "pending" || task.schedulerStatus) return;
    try {
      await ElMessageBox.confirm("确认删除这个任务？", "警告", {
        confirmButtonText: "删除",
        cancelButtonText: "取消",
        type: "warning",
      });
      await apiDeleteTask(task.taskId);
      allTasks.value = allTasks.value.filter((item) => item.taskId !== task.taskId);
      total.value = Math.max(0, total.value - 1);
      if (selectedTaskId.value === task.taskId) {
        selectedTaskId.value = null;
      }
      message.value = "任务已删除。";
      error.value = "";
      if (allTasks.value.length === 0 && total.value > 0 && page.value > 1) {
        page.value -= 1;
      }
      await loadTasks();
    } catch (caught) {
      if (caught === "cancel") return;
      error.value = errorMessage(caught);
      message.value = "";
    }
  }

  return { startTask, retryTask, deleteTask };
}
