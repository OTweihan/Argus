<template>
  <div class="overview">
    <MetricsSummary
      :metrics="summary.completeness.metrics"
      :endpoint-count="summary.endpointCount"
      :call-graph-node-count="summary.callGraphNodeCount"
      :finding-count="summary.findingCount"
    />

    <section class="risk-panel">
      <div class="section-heading">
        <div>
          <span class="section-kicker">RISK DISTRIBUTION</span>
          <h3>发现项严重级别</h3>
        </div>
        <span class="risk-total">共 {{ summary.findingCount }} 项</span>
      </div>
      <div v-if="severityEntries.length" class="severity-bars">
        <div v-for="[sev, count] in severityEntries" :key="sev" class="severity-bar-row">
          <span :class="`severity-dot dot-${sev.toLowerCase()}`" />
          <span :class="`sev-label sev-${sev.toLowerCase()}`">{{ sev }}</span>
          <span class="sev-count">{{ count }}</span>
        </div>
      </div>
      <p v-else class="risk-empty">本次分析没有发现风险项。</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { AnalysisRunSummary } from "../../../api/task";
import MetricsSummary from "./MetricsSummary.vue";
import { SEVERITY_ORDER } from "./severity";

const props = defineProps<{ summary: AnalysisRunSummary }>();

const severityEntries = computed(() => {
  const counts = props.summary.findingSeverityCounts || {};
  return SEVERITY_ORDER.filter((s) => counts[s]).map((s) => [s, counts[s]] as const);
});
</script>

<style scoped>
.overview {
  padding: 2px 0;
}

.risk-panel {
  margin-top: 12px;
  padding: 18px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
  background: var(--surface-glass-strong);
  box-shadow: var(--shadow-xs);
}

.section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.section-kicker {
  color: var(--brand-700);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.12em;
}

.section-heading h3 {
  margin: 3px 0 0;
  color: var(--text-strong);
  font-size: 16px;
}

.risk-total,
.risk-empty {
  color: var(--text-faint);
  font-size: 12px;
}

.severity-bars {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.severity-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 132px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
}

.severity-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.dot-critical {
  color: #991b1b;
}
.dot-high {
  color: #c2410c;
}
.dot-medium {
  color: #b45309;
}
.dot-low {
  color: #2563eb;
}
.dot-info {
  color: #6b7280;
}

.sev-label {
  font-size: 12px;
  font-weight: 700;
}

.sev-critical {
  color: #991b1b;
}
.sev-high {
  color: #c2410c;
}
.sev-medium {
  color: #b45309;
}
.sev-low {
  color: #2563eb;
}
.sev-info {
  color: #6b7280;
}

.sev-count {
  margin-left: auto;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-strong);
}
</style>
