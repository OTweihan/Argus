<template>
  <div class="selector-bar">
    <span class="selector-label">选择分析执行</span>
    <el-select
      :model-value="selectedId"
      size="large"
      class="run-select"
      :disabled="loading"
      @update:model-value="$emit('select', $event as string)"
    >
      <el-option
        v-for="run in runs"
        :key="run.analysisId"
        :label="formatOption(run)"
        :value="run.analysisId"
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
  const sha = run.resolvedCommitSha ? run.resolvedCommitSha.slice(0, 8) : "";
  return `${date} — ${status}${sha ? ` (${sha})` : ""}`;
}
</script>

<style scoped>
.selector-bar {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  gap: 7px;
  min-width: min(360px, 100%);
}

.selector-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted, #4b5563);
  flex-shrink: 0;
}

.run-select {
  width: 360px;
  max-width: 100%;
}

.run-select :deep(.el-select__wrapper) {
  border: 1px solid rgba(10, 186, 181, 0.2);
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: var(--shadow-xs);
}

.run-select :deep(.el-select__wrapper.is-focused) {
  box-shadow:
    0 0 0 1px var(--brand-500),
    var(--shadow-ring);
}

.selector-hint {
  font-size: 12px;
  color: var(--text-faint, #9ca3af);
}

@media (max-width: 640px) {
  .selector-bar,
  .run-select {
    width: 100%;
    min-width: 0;
  }
}
</style>
