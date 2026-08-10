import { getCurrentScope, onScopeDispose, ref, watch, type Ref } from "vue";
import { listTasks as apiListTasks } from "../api";
import type { Task, TaskDisplayStatus, TaskType } from "../types";
import { errorMessage, isAbortError } from "../utils";
import { useDebounceFn } from "./useDebounceFn";

/** 列表查询参数的不可变快照：请求期间不再读取变化中的 ref，避免响应与条件错位。 */
interface TaskListQuery {
  status?: TaskDisplayStatus | "";
  projectId?: string;
  taskType?: TaskType | "";
  q?: string;
  offset: number;
  limit: number;
}

export function useTaskList(opts: {
  allTasks: Ref<Task[]>;
  /** 列表加载失败（非取消、非被更新查询取代）时的上报回调。 */
  onError?: (msg: string) => void;
}) {
  const { allTasks, onError } = opts;
  const taskStatusFilter = ref<TaskDisplayStatus | "">("");
  const taskProjectFilter = ref("");
  const taskTypeFilter = ref<TaskType | "">("");
  const taskSearchQuery = ref("");
  const page = ref(1);
  const pageSize = ref(20);
  const total = ref(0);
  const taskLoading = ref(false);

  /** 进行中的列表请求；每次新查询先取消旧请求，避免较慢的旧响应覆盖新条件结果。 */
  let inflightController: AbortController | null = null;
  /** 列表请求代次：每次 loadTasks 递增；只有最新代次能写回 allTasks/total/loading/error。 */
  let loadGeneration = 0;
  /** 组件卸载后禁止再写状态 / 上报错误。 */
  let disposed = false;

  // 需在 Vue effect scope（组件 setup / effectScope）内调用；纯函数调用场景
  // 跳过清理注册（与 useDebounceFn 一致），避免无活跃 scope 时抛错。
  if (getCurrentScope()) {
    onScopeDispose(() => {
      disposed = true;
      inflightController?.abort();
    });
  }

  async function loadTasks(): Promise<void> {
    // 取消仍在进行的旧请求。
    inflightController?.abort();
    const controller = new AbortController();
    inflightController = controller;
    const gen = ++loadGeneration;
    taskLoading.value = true;

    // 查询条件在发起瞬间定格为不可变快照。
    const query: TaskListQuery = {
      status: taskStatusFilter.value || undefined,
      projectId: taskProjectFilter.value || undefined,
      taskType: taskTypeFilter.value || undefined,
      q: taskSearchQuery.value.trim() || undefined,
      offset: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
    };

    try {
      const res = await apiListTasks(query, { signal: controller.signal });
      if (disposed || gen !== loadGeneration) return; // 组件卸载 / 已被更新查询取代
      allTasks.value = res.tasks ?? [];
      total.value = res.total;
    } catch (caught) {
      if (disposed || gen !== loadGeneration) return; // 旧查询的失败不再报错
      if (isAbortError(caught)) return; // 主动取消不是错误
      // 真实失败：上报交给调用方 —— 内部触发走 safeLoad → onError，
      // 显式调用方（loadAll / retry / delete / 事件刷新）已有自己的 try/catch。
      throw caught;
    } finally {
      if (!disposed && gen === loadGeneration) {
        taskLoading.value = false;
      }
    }
  }

  /** 内部触发（分页 / 筛选 / 搜索防抖）的加载入口：吞掉失败并统一上报。 */
  function safeLoad(): void {
    void loadTasks().catch((caught) => onError?.(errorMessage(caught)));
  }

  function onPageChange(newPage: number): void {
    page.value = newPage;
    safeLoad();
  }

  function onPageSizeChange(newSize: number): void {
    pageSize.value = newSize;
    page.value = 1;
    safeLoad();
  }

  const debouncedSearch = useDebounceFn(() => {
    page.value = 1;
    safeLoad();
  }, 300);
  watch(taskSearchQuery, debouncedSearch);

  watch([taskStatusFilter, taskProjectFilter, taskTypeFilter], () => {
    page.value = 1;
    safeLoad();
  });

  return {
    taskStatusFilter,
    taskProjectFilter,
    taskTypeFilter,
    taskSearchQuery,
    page,
    pageSize,
    total,
    taskLoading,
    loadTasks,
    onPageChange,
    onPageSizeChange,
  };
}
