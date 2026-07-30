<template>
  <div class="selector-bar">
    <span class="selector-label">分析执行</span>
    <el-select
      :model-value="selectedId" size="small"
      style="width: 260px" :disabled="loading" @update:model-value="$emit('select', $event as string)"
    >
      <el-option
        v-for="run in runs" :key="run.analysisId"
        :label="formatOption(run)" :value="run.analysisId"
      />
    </el-select>
    <span v-if="loading" class="selector-hint">加载中...</span>
  </div>
</template>

<script setup lang="ts">
import { formatDate } from "../../../utils";
import type { AnalysisRunSummary } from "../../../api/task";

defineProps<{
  runs: AnalysisRunSummary[];
  selectedId: string | null;
  loading: boolean;
}>();

defineEmits<{
  select: [analysisId: string];
}>();

const STATUS_LABELS: Record<string, string> = {
  QUEUED: "排队中",
  SUBMITTING: "提交中",
  RUNNING: "运行中",
  SUCCEEDED: "成功",
  FAILED: "失败",
  TIMED_OUT: "超时",
  CANCELLED: "已取消",
  STOPPED_WAITING: "已停止等待",
};

function formatOption(run: AnalysisRunSummary): string {
  const date = formatDate(run.createdAt);
  const status = STATUS_LABELS[run.runStatus] || run.runStatus;
  const sha = run.resolvedCommitSha
    ? run.resolvedCommitSha.slice(0, 8)
    : "";
  return `${date} — ${status}${sha ? ` (${sha})` : ""}`;
}
</script>

<style scoped>
.selector-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 0 12px;
}

.selector-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-faint, #6b7280);
  flex-shrink: 0;
}

.selector-hint {
  font-size: 12px;
  color: var(--text-faint, #9ca3af);
}
</style>
