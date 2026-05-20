/**
 * LLM 调试页的"列表 + 过滤 + 选中"数据层。
 *
 * 把原本散在 LLMDebugTab.vue setup 里的 traces / loading / filter ref 集中到
 * 一个 composable，让组件本身只剩"编排 + 视图"，方便单测过滤逻辑。
 */
import { computed, ref, watch } from "vue";

import { getTaskTraces } from "../../../api";
import type { LLMTraceRecord } from "../../../types";
import { errorMessage } from "../../../utils";

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
        loading.value = true;
        loadError.value = "";
        try {
            traces.value = await getTaskTraces(opts.taskId());
        } catch (caught) {
            loadError.value = errorMessage(caught);
        } finally {
            loading.value = false;
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
