import { computed, watch, type Ref } from "vue";

import { ElMessage } from "element-plus";
import type { Task } from "../types";
import { compact, displayTaskName } from "../utils";
import type { ViewKey } from "./useNavigation";

/** 顶栏派生与全局反馈：viewTitle 计算 + error/message 的节流 toast 监听。 */
export function useTopBar(opts: {
  view: Ref<ViewKey>;
  selectedTask: Ref<Task | null>;
  error: Ref<string>;
  message: Ref<string>;
}) {
  const { view, selectedTask, error, message } = opts;

  const viewTitle = computed(() => {
    if (view.value === "task-detail") {
      const task = selectedTask.value;
      if (!task) return "报告详情";
      // 顶部标题优先使用任务名（含重试次数），与任务列表口径一致；
      // 旧任务缺失 name 时回落到目标文案。
      const name = task.name?.trim();
      return name ? displayTaskName(task) : compact(task.goal, 60);
    }
    return (
      {
        dashboard: "仪表盘",
        projects: "项目管理",
        tasks: "任务管理",
        regression: "回归测试",
        models: "模型配置",
        diagnostics: "诊断中心",
      }[view.value] ?? ""
    );
  });

  let _lastErrorToast = 0;
  watch(error, (val) => {
    if (val) {
      const now = Date.now();
      if (now - _lastErrorToast < 2000) return;
      _lastErrorToast = now;
      ElMessage({ message: val, type: "error", duration: 5000 });
    }
  });

  let _lastMessageToast = 0;
  watch(message, (val) => {
    if (val) {
      const now = Date.now();
      if (now - _lastMessageToast < 2000) return;
      _lastMessageToast = now;
      ElMessage({ message: val, type: "success", duration: 3000 });
    }
  });

  return { viewTitle };
}
