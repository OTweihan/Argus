<template>
  <div class="overview-panel">
    <div class="panel-toolbar">
      <div>
        <h3>概览</h3>
        <p>快速判断当前实例健康度与近期异常。</p>
      </div>
      <el-button type="primary" plain :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-alert v-if="error" type="error" :closable="false" :title="error" />

    <div v-if="data" class="cards">
      <div class="card">
        <div class="label">Run ID</div>
        <div class="value mono">{{ data.runId }}</div>
      </div>
      <div class="card">
        <div class="label">近 1 小时 ERROR</div>
        <div class="value">{{ data.errorCountLastHour }}</div>
      </div>
      <div v-if="data.logsUsage" class="card">
        <div class="label">日志占用</div>
        <div class="value">{{ formatBytes(data.logsUsage.totalBytes) }}</div>
      </div>
      <div class="card">
        <div class="label">最近检查</div>
        <div class="value">{{ formatTimestamp(data.checkedAt) }}</div>
      </div>
    </div>

    <el-table v-if="data" :data="data.services" size="small" class="svc">
      <el-table-column label="组件" prop="name" width="120" />
      <el-table-column label="状态" prop="status" width="120" />
      <el-table-column label="说明" prop="detail" min-width="200" show-overflow-tooltip />
    </el-table>

    <h4 v-if="data?.recentSystemEvents?.length">最近系统事件</h4>
    <el-table
      v-if="data?.recentSystemEvents?.length"
      :data="data.recentSystemEvents"
      size="small"
    >
      <el-table-column label="时间" width="180">
        <template #default="{ row }">{{ formatTimestamp(row.timestamp) }}</template>
      </el-table-column>
      <el-table-column label="事件" prop="message" min-width="220" />
      <el-table-column label="级别" prop="level" width="90" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { getDiagnosticsOverview } from "../../api/diagnostics";
import { errorMessage } from "../../utils";
import { formatBytes, formatTimestamp } from "./utils";

type OverviewBody = Awaited<ReturnType<typeof getDiagnosticsOverview>>;

const loading = ref(false);
const error = ref("");
const data = ref<OverviewBody | null>(null);
let controller: AbortController | null = null;

async function load() {
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = "";
  try {
    data.value = await getDiagnosticsOverview({ signal: controller.signal });
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") return;
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void load();
});
onUnmounted(() => {
  controller?.abort();
});
</script>

<style scoped>
.overview-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.panel-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.panel-toolbar h3 {
  margin: 0 0 4px;
}
.panel-toolbar p {
  margin: 0;
  color: var(--text-faint);
  font-size: 13px;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
}
.card {
  padding: 12px 14px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
  background: var(--surface-glass);
}
.label {
  color: var(--text-faint);
  font-size: 12px;
}
.value {
  margin-top: 6px;
  font-size: 16px;
  font-weight: 650;
}
.mono {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 13px;
}
h4 {
  margin: 4px 0 0;
}
</style>
