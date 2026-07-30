<template>
  <div class="overview">
    <MetricsSummary
      :metrics="summary.completeness.metrics"
      :endpoint-count="summary.endpointCount"
      :call-graph-node-count="summary.callGraphNodeCount"
      :finding-count="summary.findingCount"
    />

    <div v-if="severityEntries.length" class="severity-section">
      <div class="section-title">
        发现项严重级别
      </div>
      <div class="severity-bars">
        <div v-for="[sev, count] in severityEntries" :key="sev" class="severity-bar-row">
          <span :class="`sev-label sev-${sev.toLowerCase()}`">{{ sev }}</span>
          <span class="sev-count">{{ count }}</span>
        </div>
      </div>
    </div>

    <div v-if="summary.resolvedCommitSha" class="snapshot-info">
      <div class="section-title">
        源码快照
      </div>
      <div class="snapshot-row">
        <span class="snap-key">Commit SHA</span>
        <span class="snap-val mono">{{ summary.resolvedCommitSha.slice(0, 8) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { AnalysisRunSummary } from "../../../api/task";
import MetricsSummary from "./MetricsSummary.vue";

const props = defineProps<{ summary: AnalysisRunSummary }>();

const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];

const severityEntries = computed(() => {
  const counts = props.summary.findingSeverityCounts || {};
  return SEVERITY_ORDER
    .filter((s) => counts[s])
    .map((s) => [s, counts[s]] as const);
});
</script>

<style scoped>
.overview {
  padding: 4px 0;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-faint);
  margin-bottom: 8px;
  margin-top: 16px;
}

.severity-bars {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.severity-bar-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
}

.sev-label {
  font-size: 12px;
  font-weight: 700;
}

.sev-critical { color: #991b1b; }
.sev-high { color: #c2410c; }
.sev-medium { color: #b45309; }
.sev-low { color: #2563eb; }
.sev-info { color: #6b7280; }

.sev-count {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-strong);
}

.snapshot-info {
  margin-top: 8px;
}

.snapshot-row {
  display: flex;
  gap: 8px;
  padding: 4px 0;
}

.snap-key {
  font-size: 12px;
  color: var(--text-faint);
  min-width: 80px;
}

.snap-val {
  font-size: 13px;
  color: var(--text-strong);
}

.snap-val.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}
</style>
