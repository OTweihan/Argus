<template>
  <div class="trace-panel">
    <div class="panel-heading">
      <div>
        <h3>请求追踪</h3>
        <p>使用 Request ID 还原单次请求在服务内的处理顺序。</p>
      </div>
    </div>
    <el-form inline class="trace-search" @submit.prevent>
      <el-form-item label="Request ID">
        <el-input
          v-model="requestId"
          placeholder="输入请求链路 ID（req_…）"
          clearable
          style="width: 340px"
          @keyup.enter="doTrace"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="loading" @click="doTrace">追踪</el-button>
      </el-form-item>
    </el-form>

    <el-alert
      v-if="searched && items.length === 0"
      type="info"
      :closable="false"
      title="未找到该 Request ID 的日志。第一阶段仅 Python 结构化日志携带 requestId；Java/前端链路贯通将在日志基础规范阶段补齐。"
    />

    <el-timeline v-else-if="items.length" class="trace-timeline">
      <el-timeline-item
        v-for="item in items"
        :key="item.eventId"
        :timestamp="formatTimestamp(item.timestamp)"
        :type="timelineType(item.level)"
        placement="top"
      >
        <div class="trace-card">
          <div class="trace-head">
            <span class="trace-component">{{ item.component }}</span>
            <el-tag :type="levelTagType(item.level)" size="small">{{ item.level }}</el-tag>
            <span class="trace-module">{{ item.module || "-" }}</span>
          </div>
          <div class="trace-message">{{ item.message }}</div>
          <div v-if="item.exception" class="trace-exception">{{ item.exception }}</div>
        </div>
      </el-timeline-item>
    </el-timeline>

    <el-empty v-else description="输入 Request ID 还原一次请求的完整处理过程" :image-size="80" />
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { traceDiagnosticsRequest, type DiagnosticsLogEntry } from "../../api/diagnostics";
import { errorMessage } from "../../utils";
import { formatTimestamp, levelTagType } from "./utils";

const requestId = ref("");
const items = ref<DiagnosticsLogEntry[]>([]);
const loading = ref(false);
const searched = ref(false);
let traceVersion = 0;

function timelineType(level: string): "danger" | "warning" | "primary" {
  const upper = level.toUpperCase();
  if (upper === "ERROR" || upper === "CRITICAL" || upper === "FATAL") return "danger";
  if (upper === "WARN" || upper === "WARNING") return "warning";
  return "primary";
}

async function doTrace(): Promise<void> {
  const trimmed = requestId.value.trim();
  if (!trimmed) {
    searched.value = false;
    items.value = [];
    return;
  }
  const requestVersion = ++traceVersion;
  loading.value = true;
  searched.value = true;
  items.value = [];
  try {
    const body = await traceDiagnosticsRequest(trimmed);
    if (requestVersion === traceVersion) items.value = body.items ?? [];
  } catch (caught) {
    if (requestVersion === traceVersion) ElMessage.error(errorMessage(caught));
  } finally {
    if (requestVersion === traceVersion) loading.value = false;
  }
}
</script>

<style scoped>
.trace-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-heading h3 {
  margin: 0;
  color: var(--text-strong);
  font-size: 16px;
}

.panel-heading p {
  margin: 5px 0 0;
  color: var(--text-faint);
  font-size: 12px;
}

.trace-search {
  padding: 14px 14px 0;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: rgba(248, 250, 252, 0.72);
}

.trace-timeline {
  padding-left: 4px;
}

.trace-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 13px 15px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.7);
  box-shadow: var(--shadow-xs);
}

.trace-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.trace-component {
  font-weight: 600;
  text-transform: uppercase;
  font-size: 12px;
  color: var(--brand-700, #079994);
}

.trace-module {
  color: var(--text-faint, #6b7280);
  font-size: 12px;
}

.trace-message {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12.5px;
  word-break: break-all;
}

.trace-exception {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  color: #b91c1c;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
