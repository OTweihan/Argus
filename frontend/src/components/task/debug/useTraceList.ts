/**
 * LLM 调试页的"列表 + 过滤 + 选中"数据层。
 *
 * 把原本散在 LLMDebugTab.vue setup 里的 traces / loading / filter ref 集中到
 * 一个 composable，让组件本身只剩"编排 + 视图"，方便单测过滤逻辑。
 */
import { computed, getCurrentScope, onScopeDispose, ref, watch } from "vue";

import { getTaskTraces } from "../../../api";
import type { LLMTraceRecord } from "../../../types";
import { errorMessage, isAbortError } from "../../../utils";

export type TracePhaseFilter = "" | "planner" | "evaluator";

export interface UseTraceListOptions {
  /** 任务 ID，可响应式：变化时自动重新拉取并清空选中。 */
  taskId: () => string;
}

export function useTraceList(opts: UseTraceListOptions) {
  const traces = ref<LLMTraceRecord[]>([]);
  const loading = ref(true);
  const loadError = ref("");
  const selectedTrace = ref<LLMTraceRecord | null>(null);
  const phaseFilter = ref<TracePhaseFilter>("");
  const hideStarted = ref(true);

  // 代次守卫 + 中止：taskId 变化/重拉时丢弃过期响应并取消在途请求，
  // 防止慢的旧任务 traces 覆盖新任务数据（契约上本 composable 声明支持
  // 响应式 taskId，防护不能依赖调用方用 :key 重挂载兜底）。
  let requestSeq = 0;
  let tracesAbort: AbortController | null = null;

  if (getCurrentScope()) {
    onScopeDispose(() => tracesAbort?.abort());
  }

  const filteredTraces = computed(() => {
    let list = traces.value;
    if (phaseFilter.value) {
      list = list.filter((t) => t.phase === phaseFilter.value);
    }
    if (hideStarted.value) {
      list = list.filter((t) => t.event !== "task.llm.started");
    }
    return list;
  });

  /**
   * 过滤条件变化时维护"选中态有效性"：
   * 若当前选中项在最新结果集中不存在，回退到首项（或清空）。
   * 不放进 watch 里是因为 UI 习惯于用户改 filter → onChange 一次性触发，
   * 而 traces 自身的变化不需要重置选中（避免新事件流入抢走焦点）。
   */
  function onFilterChange(): void {
    const current = selectedTrace.value;
    if (current && !filteredTraces.value.includes(current)) {
      selectedTrace.value = filteredTraces.value[0] ?? null;
    }
  }

  async function loadTraces(): Promise<void> {
    const seq = ++requestSeq;
    tracesAbort?.abort();
    const controller = new AbortController();
    tracesAbort = controller;
    loading.value = true;
    loadError.value = "";
    try {
      const rows = await getTaskTraces(opts.taskId(), { signal: controller.signal });
      if (seq !== requestSeq) return;
      traces.value = rows;
    } catch (caught) {
      if (seq !== requestSeq || isAbortError(caught)) return;
      loadError.value = errorMessage(caught);
    } finally {
      if (seq === requestSeq) loading.value = false;
    }
  }

  // taskId 变化时自动重新拉取并清空已选；初始挂载也会触发一次（immediate）。
  watch(
    () => opts.taskId(),
    () => {
      selectedTrace.value = null;
      void loadTraces();
    },
    { immediate: true },
  );

  return {
    traces,
    loading,
    loadError,
    selectedTrace,
    phaseFilter,
    hideStarted,
    filteredTraces,
    onFilterChange,
    loadTraces,
  };
}
