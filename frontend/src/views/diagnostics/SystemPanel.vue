<template>
  <div class="system-panel">
    <div class="panel-toolbar">
      <div>
        <h3>系统信息</h3>
        <p>当前部署实例的版本、路径与运行环境摘要。</p>
      </div>
      <el-button type="primary" plain :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-alert v-if="error" type="error" :closable="false" :title="error" class="err" />

    <el-descriptions v-if="info" :column="2" border class="info-card">
      <el-descriptions-item label="Argus 版本">{{ info.argusVersion }}</el-descriptions-item>
      <el-descriptions-item label="Python 版本">{{ info.pythonVersion }}</el-descriptions-item>
      <el-descriptions-item label="Run ID">
        <code>{{ info.runId }}</code>
      </el-descriptions-item>
      <el-descriptions-item label="部署模式">{{ info.deploymentMode }}</el-descriptions-item>
      <el-descriptions-item label="主机">{{ info.hostname }}</el-descriptions-item>
      <el-descriptions-item label="PID">{{ info.pid }}</el-descriptions-item>
      <el-descriptions-item label="OS">{{ info.osName }} {{ info.osRelease }}</el-descriptions-item>
      <el-descriptions-item label="架构">{{ info.architecture }}</el-descriptions-item>
      <el-descriptions-item label="启动时间">{{ formatTimestamp(info.startedAt) }}</el-descriptions-item>
      <el-descriptions-item label="运行时长">{{ formatDuration(info.uptimeSeconds) }}</el-descriptions-item>
      <el-descriptions-item label="日志目录" :span="2">{{ info.logsDirectory }}</el-descriptions-item>
      <el-descriptions-item label="数据目录" :span="2">{{ info.dataDirectory }}</el-descriptions-item>
      <el-descriptions-item label="Java Analyzer">{{ info.javaAnalyzerUrl }}</el-descriptions-item>
      <el-descriptions-item label="Java 运行时日志">
        <el-tag :type="info.javaRuntimeLogsPresent ? 'success' : 'info'" size="small">
          {{ info.javaRuntimeLogsPresent ? "已检测到" : "尚未写入" }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item v-if="info.javaStatus" label="Java 状态">
        {{ info.javaStatus.status }}
        <span v-if="info.javaStatus.detail" class="muted"> — {{ info.javaStatus.detail }}</span>
      </el-descriptions-item>
      <el-descriptions-item v-if="info.disk" label="磁盘">
        可用 {{ formatBytes(info.disk.freeBytes) }} / 共 {{ formatBytes(info.disk.totalBytes) }}
      </el-descriptions-item>
    </el-descriptions>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { getDiagnosticsSystem } from "../../api/diagnostics";
import { errorMessage } from "../../utils";
import { formatBytes, formatDuration, formatTimestamp } from "./utils";

type SystemBody = Awaited<ReturnType<typeof getDiagnosticsSystem>>;

const loading = ref(false);
const error = ref("");
const info = ref<SystemBody | null>(null);
let controller: AbortController | null = null;

async function load() {
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = "";
  try {
    info.value = await getDiagnosticsSystem({ signal: controller.signal });
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
.system-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
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
.info-card {
  border-radius: var(--radius-md);
}
.muted {
  color: var(--text-faint);
}
code {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
}
.err {
  border-radius: var(--radius-md);
}
</style>
