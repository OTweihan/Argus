import type { Ref } from "vue";
import type { ModelConfig, Project, Task, TaskDisplayStatus } from "../types";
import { useTaskList } from "./useTaskList";
import { useTaskSelection } from "./useTaskSelection";
import { useTaskForm } from "./useTaskForm";
import { useTaskActions } from "./useTaskActions";

// 兼容旧导入路径：表单状态类型与默认值工厂现由 useTaskForm 提供。
export { defaultTaskFormState, type TaskFormState } from "./useTaskForm";

/** 任务页组合入口：列表 + 选中态 + 表单 + 生命周期操作，均为薄装配。 */
export function useTasks(opts: {
  allTasks: Ref<Task[]>;
  projects: Ref<Project[]>;
  models: Ref<ModelConfig[]>;
  error: Ref<string>;
  message: Ref<string>;
  formErrors: Record<string, string>;
  view: Ref<string>;
}) {
  const { allTasks, projects, error, message, formErrors, view } = opts;

  const taskList = useTaskList({
    allTasks,
    // 列表内部触发（分页/筛选/搜索防抖）的失败上报到共享 error ref；
    // 显式调用方（loadAll / retry / delete / 事件刷新）仍由各自 try/catch 处理。
    onError: (msg) => {
      error.value = msg;
    },
  });
  const taskSelection = useTaskSelection({ allTasks, view, error });

  const taskStatuses: TaskDisplayStatus[] = [
    "pending",
    "queued",
    "running",
    "completed",
    "failed",
    "timeout",
    "cancelled",
  ];

  const taskFormApi = useTaskForm({
    allTasks,
    projects,
    error,
    message,
    formErrors,
    selectedTaskId: taskSelection.selectedTaskId,
    selectedTask: taskSelection.selectedTask,
  });
  const taskActionApi = useTaskActions({
    allTasks,
    error,
    message,
    loadTasks: taskList.loadTasks,
    total: taskList.total,
    page: taskList.page,
    selectedTaskId: taskSelection.selectedTaskId,
  });

  return {
    /* task list */
    ...taskList,
    /* task selection */
    ...taskSelection,
    /* form */
    ...taskFormApi,
    taskStatuses,
    /* actions */
    ...taskActionApi,
  };
}
