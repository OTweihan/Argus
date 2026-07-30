/**
 * 白盒分析结果 composable — 获取 AnalysisRun 摘要、分页子资源
 *
 * 竞态保护：请求序列号守卫，快速切换 taskId/analysisId 时丢弃旧结果
 */
import { ref, watch, type Ref } from "vue";
import {
    getAnalysisRunSummary,
    listAnalysisRuns,
    type AnalysisRunSummary,
} from "../api/task";
import { errorMessage } from "../utils";

export function useWhiteboxResult(
    taskId: Ref<string | null>,
    analysisId: Ref<string | null>,
) {
    const summary = ref<AnalysisRunSummary | null>(null);
    const runs = ref<AnalysisRunSummary[]>([]);
    const loading = ref(false);
    const error = ref("");

    let requestSeq = 0;

    async function loadRun(): Promise<void> {
        if (!taskId.value || !analysisId.value) {
            summary.value = null;
            return;
        }
        const seq = ++requestSeq;
        error.value = "";
        loading.value = true;
        try {
            const result = await getAnalysisRunSummary(
                taskId.value, analysisId.value,
            );
            if (seq !== requestSeq) return;
            summary.value = result;
        } catch (e) {
            if (seq !== requestSeq) return;
            error.value = errorMessage(e);
        } finally {
            if (seq === requestSeq) loading.value = false;
        }
    }

    async function loadRuns(): Promise<void> {
        if (!taskId.value) return;
        try {
            const page = await listAnalysisRuns(taskId.value, 0, 20);
            runs.value = page.items;
        } catch {
            // 静默忽略
        }
    }

    async function selectRun(aid: string): Promise<void> {
        analysisId.value = aid;
        await loadRun();
    }

    watch([taskId, analysisId], () => {
        if (taskId.value && analysisId.value) {
            loadRun();
        } else if (taskId.value) {
            loadRuns();
        }
    }, { immediate: true });

    return {
        summary,
        runs,
        loading,
        error,
        loadRun,
        loadRuns,
        selectRun,
    };
}
