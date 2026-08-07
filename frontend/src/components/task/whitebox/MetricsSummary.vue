<template>
  <div class="metrics-grid">
    <div class="metric-card">
      <span class="metric-value">{{ formattedNumber(metrics.eligibleSourceFiles) }}</span>
      <span class="metric-label">源文件</span>
    </div>
    <div class="metric-card">
      <span class="metric-value">{{ formattedNumber(metrics.parsedSourceFiles) }}</span>
      <span class="metric-label">已解析</span>
    </div>
    <div class="metric-card metric-card-primary">
      <span class="metric-value">
        {{ parseRate === null ? "-" : parseRate }}{{ parseRate === null ? "" : "%" }}
      </span>
      <span class="metric-label">解析率</span>
      <span class="metric-progress" aria-hidden="true">
        <span :style="{ width: `${parseRate ?? 0}%` }" />
      </span>
    </div>
    <div class="metric-card">
      <span class="metric-value">{{ formattedNumber(metrics.totalCalls) }}</span>
      <span class="metric-label">调用</span>
    </div>
    <div class="metric-card metric-card-primary">
      <span class="metric-value">
        {{ callRate === null ? "-" : callRate }}{{ callRate === null ? "" : "%" }}
      </span>
      <span class="metric-label">调用解析率</span>
      <span class="metric-progress" aria-hidden="true">
        <span :style="{ width: `${callRate ?? 0}%` }" />
      </span>
    </div>
    <div class="metric-card">
      <span class="metric-value">{{ formattedNumber(endpointCount) }}</span>
      <span class="metric-label">端点</span>
    </div>
    <div class="metric-card">
      <span class="metric-value">{{ formattedNumber(callGraphNodeCount) }}</span>
      <span class="metric-label">调用图节点</span>
    </div>
    <div class="metric-card">
      <span class="metric-value">{{ formattedNumber(findingCount) }}</span>
      <span class="metric-label">发现项</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  metrics: { eligibleSourceFiles: number; parsedSourceFiles: number; totalCalls: number; resolvedCalls: number };
  endpointCount: number;
  callGraphNodeCount: number;
  findingCount: number;
}>();

const parseRate = computed(() => props.metrics.eligibleSourceFiles
  ? Math.round(props.metrics.parsedSourceFiles / props.metrics.eligibleSourceFiles * 100)
  : null);

const callRate = computed(() => props.metrics.totalCalls
  ? Math.round(props.metrics.resolvedCalls / props.metrics.totalCalls * 100)
  : null);

function formattedNumber(n: number): string {
  if (n >= 10000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
</script>

<style scoped>
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 10px;
}

.metric-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-height: 96px;
  padding: 15px 16px;
  background: var(--surface-glass-strong);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md, 12px);
  box-shadow: var(--shadow-xs);
  transition: transform var(--transition-fast), border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.metric-card:hover {
  transform: translateY(-2px);
  border-color: rgba(10, 186, 181, 0.34);
  box-shadow: var(--shadow-sm);
}

.metric-card-primary {
  background: linear-gradient(145deg, rgba(236, 254, 253, 0.95), rgba(255, 255, 255, 0.92));
}

.metric-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--brand-700, #087b78);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
}

.metric-label {
  font-size: 12px;
  color: var(--text-faint);
  margin-top: 4px;
  font-weight: 600;
}

.metric-progress {
  display: block;
  width: 100%;
  height: 4px;
  margin-top: 11px;
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: var(--brand-100);
}

.metric-progress > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--brand-gradient);
  transition: width var(--transition-slow);
}

@media (max-width: 1080px) {
  .metrics-grid {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}

@media (max-width: 540px) {
  .metrics-grid {
    grid-template-columns: 1fr;
  }
}
</style>
