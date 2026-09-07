<template>
  <div class="overview-panel">
    <div class="panel-toolbar">
      <div>
        <h3>概览</h3>
        <p>快速判断当前实例健康度与近期异常。</p>
      </div>
      <div class="toolbar-actions">
        <el-button :loading="bundleLoading" @click="downloadBundle">下载诊断包</el-button>
        <el-button type="primary" plain :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :closable="false" :title="error" />
    <el-alert
      v-if="bundleHint"
      type="info"
      :closable="true"
      :title="bundleHint"
      @close="bundleHint = ''"
    />

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
import {
  createAndDownloadDiagnosticsBundle,
  getDiagnosticsOverview,
} from "../../api/diagnostics";
import { errorMessage } from "../../utils";
import { formatBytes, formatTimestamp } from "./utils";

type OverviewBody = Awaited<ReturnType<typeof getDiagnosticsOverview>>;

const loading = ref(false);
const bundleLoading = ref(false);
const error = ref("");
const bundleHint = ref("");
const data = ref<OverviewBody | null>(null);
let controller: AbortController | null = null;
let bundleController: AbortController | null = null;

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

async function downloadBundle() {
  bundleController?.abort();
  bundleController = new AbortController();
  bundleLoading.value = true;
  bundleHint.value = "";
  try {
    const meta = await createAndDownloadDiagnosticsBundle(
      // WARN 作为 min-level：含 WARN/ERROR/CRITICAL/FATAL
      { maxEvents: 2000, levels: ["WARN"] },
      { signal: bundleController.signal },
    );
    const parts = [`已下载诊断包（${meta.eventCount} 条日志）`];
    if (meta.truncated) parts.push("已达条数上限，部分日志未纳入");
    if (meta.scanLimited) parts.push("扫描预算截断");
    bundleHint.value = parts.join("；");
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") return;
    if ((err as { code?: string })?.code === "REQUEST_ABORTED") return;
    error.value = errorMessage(err);
  } finally {
    bundleLoading.value = false;
  }
}

onMounted(() => {
  void load();
});
onUnmounted(() => {
  controller?.abort();
  bundleController?.abort();
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
  gap: 12px;
}
.toolbar-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
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
  margin-bottom: 4px;
}
.value {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-strong);
}
.mono {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 13px;
  word-break: break-all;
}
.svc {
  width: 100%;
}
h4 {
  margin: 8px 0 0;
  font-size: 14px;
}
</style>
