<template>
  <div class="dbg-wrapper">
    <div class="dbg-main">
      <TraceListPanel
        :traces="filteredTraces"
        :loading="loading"
        :load-error="loadError"
        :selected-trace-id="selectedTrace?.traceId ?? null"
        :phase-filter="phaseFilter"
        :hide-started="hideStarted"
        @select="selectedTrace = $event"
        @update:phase-filter="phaseFilter = $event"
        @update:hide-started="hideStarted = $event"
        @filter-change="onFilterChange"
        @download="downloadDebugBundle"
      />

      <TraceDetailPanel v-if="selectedTrace" :trace="selectedTrace" />
      <el-empty v-else class="dbg-empty-detail" description="选择左侧追踪记录查看详情" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { debugBundlePath, openAuthenticatedResource } from "../../api";
import TraceDetailPanel from "./debug/TraceDetailPanel.vue";
import TraceListPanel from "./debug/TraceListPanel.vue";
import { useTraceList } from "./debug/useTraceList";

const props = defineProps<{ taskId: string }>();

const {
  loading,
  loadError,
  selectedTrace,
  phaseFilter,
  hideStarted,
  filteredTraces,
  onFilterChange,
} = useTraceList({ taskId: () => props.taskId });

async function downloadDebugBundle(): Promise<void> {
  await openAuthenticatedResource(
    debugBundlePath(props.taskId),
    `debug-${props.taskId}.zip`,
  );
}
</script>

<style scoped>
.dbg-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  background: rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.dbg-main {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

.dbg-empty-detail {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
