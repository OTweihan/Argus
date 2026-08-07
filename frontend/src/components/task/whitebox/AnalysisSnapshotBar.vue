<template>
  <div class="snapshot-bar">
    <div class="snapshot-row">
      <span class="snap-label">分析 ID</span>
      <span class="snap-value mono">{{ summary.analysisId }}</span>
    </div>
    <div v-if="summary.resolvedCommitSha" class="snapshot-row">
      <span class="snap-label">Commit</span>
      <span class="snap-value mono">{{ summary.resolvedCommitSha.slice(0, 8) }}</span>
    </div>
    <div class="snapshot-row">
      <span class="snap-label">状态</span>
      <span class="snap-value">
        <el-tag :type="statusTagType" size="small">{{ statusLabel }}</el-tag>
      </span>
    </div>
    <div v-if="summary.externalJobId" class="snapshot-row">
      <span class="snap-label">远端作业</span>
      <span class="snap-value mono">{{ summary.externalJobStatus || summary.externalJobId }}</span>
    </div>
    <div class="snapshot-row">
      <span class="snap-label">执行时间</span>
      <span class="snap-value">{{ formattedTime }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { formatDate } from "../../../utils";
import type { AnalysisRunSummary } from "../../../api/task";

const props = defineProps<{ summary: AnalysisRunSummary }>();

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

const statusLabel = computed(() => STATUS_LABELS[props.summary.runStatus] || props.summary.runStatus);

const statusTagType = computed(() => {
  switch (props.summary.runStatus) {
    case "SUCCEEDED": return "success";
    case "FAILED":
    case "TIMED_OUT": return "danger";
    case "RUNNING":
    case "SUBMITTING": return "warning";
    default: return "info";
  }
});

const formattedTime = computed(() => {
  const start = props.summary.startedAt || props.summary.createdAt;
  return start ? formatDate(start) : "-";
});
</script>

<style scoped>
.snapshot-bar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 14px 20px;
  min-height: 100%;
  padding: 16px 18px;
  background: var(--surface-glass-strong);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
}

.snapshot-row {
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.snap-label {
  font-size: 11px;
  color: var(--text-faint);
  font-weight: 700;
  letter-spacing: 0.04em;
}

.snap-value {
  max-width: 100%;
  overflow: hidden;
  font-size: 13px;
  color: var(--text-strong);
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snap-value.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}
</style>
