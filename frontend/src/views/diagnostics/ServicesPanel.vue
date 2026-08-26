<template>
  <div class="services-panel">
    <div class="panel-toolbar">
      <el-button size="large" type="primary" plain :loading="loading" @click="loadServices">
        刷新状态
      </el-button>
      <span class="hint">每 {{ REFRESH_SECONDS }} 秒自动刷新</span>
      <span v-if="checkedAt" class="hint">最近检查：{{ formatTimestamp(checkedAt) }}</span>
    </div>

    <el-table v-loading="loading" :data="services" size="default" class="services-table">
      <el-table-column label="组件" prop="name" width="120">
        <template #default="{ row }">
          <span class="service-name">{{ serviceName(row.name) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="版本" prop="version" width="100">
        <template #default="{ row }">{{ row.version ?? "-" }}</template>
      </el-table-column>
      <el-table-column label="PID" prop="pid" width="90">
        <template #default="{ row }">{{ row.pid ?? "-" }}</template>
      </el-table-column>
      <el-table-column label="地址" width="180">
        <template #default="{ row }">
          <span v-if="row.host || row.port">{{ row.host ?? "-" }}{{ row.port ? `:${row.port}` : "" }}</span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="运行时长" width="130">
        <template #default="{ row }">{{ formatDuration(row.uptimeSeconds) }}</template>
      </el-table-column>
      <el-table-column label="响应耗时" width="110">
        <template #default="{ row }">
          <span v-if="row.latencyMs !== null && row.latencyMs !== undefined">{{ row.latencyMs }} ms</span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="说明" prop="detail" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.detail ?? "-" }}</template>
      </el-table-column>
    </el-table>

    <el-descriptions v-if="logsUsage" title="日志目录占用" :column="3" border class="usage-card">
      <el-descriptions-item label="目录">{{ logsUsage.path }}</el-descriptions-item>
      <el-descriptions-item label="占用空间">{{ formatBytes(logsUsage.totalBytes) }}</el-descriptions-item>
      <el-descriptions-item label="文件数">{{ logsUsage.fileCount }}</el-descriptions-item>
    </el-descriptions>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getDiagnosticsServices } from "../../api/diagnostics";
import { errorMessage } from "../../utils";
import { formatBytes, formatDuration, formatTimestamp } from "./utils";

const REFRESH_SECONDS = 10;

type ServicesBody = Awaited<ReturnType<typeof getDiagnosticsServices>>;
type ServiceRow = NonNullable<ServicesBody["services"]>[number];

const loading = ref(false);
const services = ref<ServiceRow[]>([]);
const logsUsage = ref<ServicesBody["logsUsage"]>(null);
const checkedAt = ref("");
let refreshTimer: number | null = null;

function serviceName(name: string): string {
  const labels: Record<string, string> = {
    python: "Python 服务",
    java: "Java 分析器",
    database: "数据库",
    web: "Web 前端",
    logs: "日志服务",
  };
  return labels[name] ?? name;
}

function statusText(status: string): string {
  const labels: Record<string, string> = {
    ok: "正常",
    unreachable: "不可达",
    unknown: "未知",
    not_ready: "未就绪",
    not_built: "未构建",
  };
  return labels[status] ?? status;
}

function statusTagType(status: string): "success" | "danger" | "info" | "warning" {
  if (status === "ok") return "success";
  if (status === "unreachable") return "danger";
  if (status === "not_ready" || status === "not_built") return "warning";
  return "info";
}

async function loadServices(): Promise<void> {
  loading.value = true;
  try {
    const body = await getDiagnosticsServices();
    services.value = body.services ?? [];
    logsUsage.value = body.logsUsage ?? null;
    checkedAt.value = body.checkedAt ?? "";
  } catch (caught) {
    ElMessage.error(errorMessage(caught));
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadServices();
  refreshTimer = window.setInterval(() => void loadServices(), REFRESH_SECONDS * 1000);
});

onUnmounted(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer);
});
</script>

<style scoped>
.services-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hint {
  color: var(--text-faint, #6b7280);
  font-size: 12px;
}
</style>
