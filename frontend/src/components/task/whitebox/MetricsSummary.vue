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
    <div class="metric-card">
      <span class="metric-value">
        {{ metrics.eligibleSourceFiles ? Math.round(metrics.parsedSourceFiles / metrics.eligibleSourceFiles * 100) : "-" }}%
      </span>
      <span class="metric-label">解析率</span>
    </div>
    <div class="metric-card">
      <span class="metric-value">{{ formattedNumber(metrics.totalCalls) }}</span>
      <span class="metric-label">调用</span>
    </div>
    <div class="metric-card">
      <span class="metric-value">
        {{ metrics.totalCalls ? Math.round(metrics.resolvedCalls / metrics.totalCalls * 100) : "-" }}%
      </span>
      <span class="metric-label">调用解析率</span>
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
defineProps<{
  metrics: { eligibleSourceFiles: number; parsedSourceFiles: number; totalCalls: number; resolvedCalls: number };
  endpointCount: number;
  callGraphNodeCount: number;
  findingCount: number;
}>();

function formattedNumber(n: number): string {
  if (n >= 10000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
</script>

<style scoped>
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}

.metric-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 8px;
  background: var(--surface-glass-strong);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm, 8px);
}

.metric-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--brand-600, #6366f1);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
}

.metric-label {
  font-size: 11px;
  color: var(--text-faint);
  margin-top: 2px;
}
</style>
