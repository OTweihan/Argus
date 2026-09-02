<template>
  <div class="events-panel">
    <div class="panel-toolbar">
      <div>
        <h3>系统事件</h3>
        <p>启动/停止等运行状态变化（本地 JSONL 投影）。</p>
      </div>
      <el-button type="primary" plain :loading="loading" @click="reload">刷新</el-button>
    </div>

    <el-alert
      v-if="scanLimited"
      type="warning"
      :closable="false"
      title="扫描达到字节预算上限，较早事件可能未纳入。"
    />

    <el-table v-loading="loading && items.length === 0" :data="items" size="small">
      <el-table-column label="时间" width="180">
        <template #default="{ row }">{{ formatTimestamp(row.timestamp) }}</template>
      </el-table-column>
      <el-table-column label="级别" width="90">
        <template #default="{ row }">
          <el-tag size="small">{{ row.level }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="事件" prop="message" min-width="220" />
      <el-table-column label="模块" prop="module" width="160" show-overflow-tooltip />
      <el-table-column label="Run ID" width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ row.runId ?? "-" }}</template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无系统事件" :image-size="64" />
      </template>
    </el-table>

    <div v-if="hasMore" class="more">
      <el-button :loading="loading" @click="loadMore">加载更多</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { listDiagnosticsEvents, type DiagnosticsLogEntry } from "../../api/diagnostics";
import { errorMessage } from "../../utils";
import { formatTimestamp } from "./utils";
import { ElMessage } from "element-plus";

const loading = ref(false);
const items = ref<DiagnosticsLogEntry[]>([]);
const hasMore = ref(false);
const scanLimited = ref(false);
const cursor = ref<string | undefined>(undefined);
let controller: AbortController | null = null;

async function fetchPage(reset: boolean) {
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  try {
    const page = await listDiagnosticsEvents(
      { limit: 50, cursor: reset ? undefined : cursor.value },
      { signal: controller.signal },
    );
    const pageItems = page.items ?? [];
    items.value = reset ? pageItems : [...items.value, ...pageItems];
    hasMore.value = Boolean(page.hasMore);
    scanLimited.value = Boolean(page.scanLimited);
    cursor.value = page.nextCursor ?? undefined;
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") return;
    ElMessage.error(errorMessage(err));
  } finally {
    loading.value = false;
  }
}

function reload() {
  cursor.value = undefined;
  void fetchPage(true);
}
function loadMore() {
  void fetchPage(false);
}

onMounted(() => {
  void fetchPage(true);
});
onUnmounted(() => {
  controller?.abort();
});
</script>

<style scoped>
.events-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.panel-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.panel-toolbar h3 {
  margin: 0 0 4px;
}
.panel-toolbar p {
  margin: 0;
  color: var(--text-faint);
  font-size: 13px;
}
.more {
  display: flex;
  justify-content: center;
}
</style>
