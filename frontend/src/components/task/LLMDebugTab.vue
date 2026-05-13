<template>
  <div class="dbg-wrapper">
    <!-- Filter bar -->
    <div class="dbg-toolbar">
      <div class="dbg-toolbar-left">
        <el-select v-model="phaseFilter" placeholder="全部阶段" clearable style="width: 140px" @change="onFilterChange">
          <el-option label="全部阶段" value="" />
          <el-option label="Planner" value="planner" />
          <el-option label="Evaluator" value="evaluator" />
        </el-select>
        <el-checkbox v-model="hideStarted" label="隐藏 started" @change="onFilterChange" />
        <span class="dbg-count">{{ filteredTraces.length }} 条追踪</span>
      </div>
      <div class="dbg-toolbar-right">
        <el-button size="small" @click="downloadDebugBundle">下载调试包</el-button>
      </div>
    </div>

    <!-- Main split -->
    <div class="dbg-main">
      <!-- Left: list -->
      <div class="dbg-list">
        <div
          v-for="trace in filteredTraces"
          :key="trace.traceId"
          :class="['dbg-item', { selected: selectedTrace === trace }]"
          @click="selectedTrace = trace"
        >
          <div class="dbg-item-header">
            <el-tag size="small" :type="eventTagType(trace.event)" class="dbg-event-tag">
              {{ eventLabel(trace.event) }}
            </el-tag>
            <el-tag size="small" effect="plain">{{ trace.phase }}</el-tag>
          </div>
          <div class="dbg-item-body">
            <span class="dbg-model">{{ trace.model || '-' }}</span>
            <span class="dbg-latency" v-if="trace.latencyMs != null && trace.latencyMs > 0">
              {{ (trace.latencyMs / 1000).toFixed(1) }}s
            </span>
          </div>
          <div class="dbg-item-time">{{ formatTime(trace.timestamp) }}</div>
        </div>
        <el-empty v-if="!filteredTraces.length" :description="loading ? '加载中...' : '无追踪记录'" />
      </div>

      <!-- Right: detail -->
      <div v-if="selectedTrace" class="dbg-detail">
        <div class="dbg-detail-header">
          <span class="dbg-detail-title">追踪详情</span>
          <div class="dbg-detail-actions">
            <el-button size="small" @click="copyPrompt">复制 Prompt</el-button>
            <el-button size="small" @click="copyRawResponse">复制 Raw Response</el-button>
          </div>
        </div>

        <div class="dbg-detail-scroll">
          <!-- Meta info -->
          <el-descriptions :column="2" border size="small" class="dbg-meta">
            <el-descriptions-item label="阶段">{{ selectedTrace.phase }}</el-descriptions-item>
            <el-descriptions-item label="事件">{{ eventLabel(selectedTrace.event) }}</el-descriptions-item>
            <el-descriptions-item label="模型">{{ selectedTrace.model || '-' }}</el-descriptions-item>
            <el-descriptions-item label="Host">{{ selectedTrace.baseUrlHost || '-' }}</el-descriptions-item>
            <el-descriptions-item label="耗时" v-if="selectedTrace.latencyMs != null">
              {{ (selectedTrace.latencyMs / 1000).toFixed(2) }}s
            </el-descriptions-item>
            <el-descriptions-item label="时间">{{ formatTime(selectedTrace.timestamp) }}</el-descriptions-item>
            <el-descriptions-item label="Prompt Tokens" v-if="tokenUsage?.prompt_tokens != null">
              {{ tokenUsage.prompt_tokens }}
            </el-descriptions-item>
            <el-descriptions-item label="Completion Tokens" v-if="tokenUsage?.completion_tokens != null">
              {{ tokenUsage.completion_tokens }}
            </el-descriptions-item>
          </el-descriptions>

          <!-- Error banner -->
          <el-alert
            v-if="selectedTrace.error"
            :title="selectedTrace.error"
            type="error"
            show-icon
            :closable="false"
            class="dbg-error"
          />
          <el-alert
            v-if="selectedTrace.parseError"
            :title="'解析失败：' + selectedTrace.parseError"
            type="warning"
            show-icon
            :closable="false"
            class="dbg-error"
          />

          <!-- System Prompt -->
          <div v-if="systemPrompt" class="dbg-section">
            <div class="dbg-section-head">
              <span class="dbg-section-title">System Prompt</span>
              <el-button size="small" link @click="copyText(systemPrompt)">复制</el-button>
            </div>
            <pre class="dbg-code">{{ systemPrompt }}</pre>
          </div>

          <!-- Input Payload -->
          <div v-if="inputPayloadStr" class="dbg-section">
            <div class="dbg-section-head">
              <span class="dbg-section-title">Input Payload</span>
              <el-button size="small" link @click="copyText(inputPayloadStr)">复制</el-button>
            </div>
            <pre class="dbg-code">{{ inputPayloadStr }}</pre>
          </div>

          <!-- Raw Response -->
          <div v-if="selectedTrace.rawResponse" class="dbg-section">
            <div class="dbg-section-head">
              <span class="dbg-section-title">Raw Response</span>
              <el-button size="small" link @click="copyText(selectedTrace.rawResponse!)">复制</el-button>
            </div>
            <pre class="dbg-code">{{ selectedTrace.rawResponse }}</pre>
          </div>

          <!-- Parsed Result -->
          <div v-if="selectedTrace.parsedResult" class="dbg-section">
            <div class="dbg-section-head">
              <span class="dbg-section-title">Parsed Result</span>
              <el-button size="small" link @click="copyText(parsedResultStr)">复制</el-button>
            </div>
            <pre class="dbg-code">{{ parsedResultStr }}</pre>
          </div>
        </div>
      </div>
      <el-empty v-else class="dbg-empty-detail" description="选择左侧追踪记录查看详情" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getTaskTraces, debugBundleUrl } from "../../api";
import type { LLMTraceRecord } from "../../types";
import { ElMessage } from "element-plus";

const props = defineProps<{ taskId: string }>();

const traces = ref<LLMTraceRecord[]>([]);
const loading = ref(true);
const selectedTrace = ref<LLMTraceRecord | null>(null);
const phaseFilter = ref("");
const hideStarted = ref(true);

const filteredTraces = computed(() => {
  let list = traces.value;
  if (phaseFilter.value) {
    list = list.filter((t) => t.phase === phaseFilter.value);
  }
  if (hideStarted.value) {
    list = list.filter((t) => t.event !== "task.llm.started");
  }
  return list;
});

const systemPrompt = computed(() => {
  return selectedTrace.value?.systemPrompt || "";
});

const tokenUsage = computed(() => {
  return selectedTrace.value?.tokenUsage || null;
});

const inputPayloadStr = computed(() => {
  const payload = selectedTrace.value?.inputPayload;
  if (!payload) return "";
  return JSON.stringify(payload, null, 2);
});

const parsedResultStr = computed(() => {
  const result = selectedTrace.value?.parsedResult;
  if (result == null) return "";
  return JSON.stringify(result, null, 2);
});

function onFilterChange() {
  // If selected trace is no longer in the list, clear selection
  if (selectedTrace.value && !filteredTraces.value.includes(selectedTrace.value)) {
    selectedTrace.value = filteredTraces.value[0] || null;
  }
}

function eventTagType(event: string): string {
  if (event === "task.llm.succeeded") return "success";
  if (event === "task.llm.failed") return "danger";
  if (event === "task.llm.parse_failed") return "warning";
  return "info";
}

function eventLabel(event: string): string {
  const labels: Record<string, string> = {
    "task.llm.started": "started",
    "task.llm.succeeded": "succeeded",
    "task.llm.failed": "failed",
    "task.llm.parse_failed": "parse_failed",
  };
  return labels[event] || event;
}

function formatTime(iso: string): string {
  if (!iso) return "-";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    ElMessage({ message: "已复制到剪贴板", type: "success", duration: 1500 });
  } catch {
    ElMessage({ message: "复制失败", type: "error", duration: 2000 });
  }
}

function copyPrompt() {
  if (!selectedTrace.value) return;
  let text = systemPrompt.value;
  if (inputPayloadStr.value) {
    text += "\n\n--- Input ---\n" + inputPayloadStr.value;
  }
  copyText(text);
}

function copyRawResponse() {
  if (!selectedTrace.value?.rawResponse) return;
  copyText(selectedTrace.value.rawResponse);
}

function downloadDebugBundle() {
  window.open(debugBundleUrl(props.taskId), "_blank");
}

onMounted(async () => {
  loading.value = true;
  try {
    traces.value = await getTaskTraces(props.taskId);
  } catch {
    // silent — show empty
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.dbg-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}

.dbg-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid #e4e7ed;
  flex-shrink: 0;
  gap: 12px;
  flex-wrap: wrap;
}

.dbg-toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dbg-toolbar-right {
  flex-shrink: 0;
}

.dbg-count {
  font-size: 12px;
  color: #909399;
}

.dbg-main {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

.dbg-list {
  width: 280px;
  min-width: 200px;
  overflow-y: auto;
  border-right: 1px solid #e4e7ed;
  padding: 4px 0;
  flex-shrink: 0;
}

.dbg-item {
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid #f0f2f5;
  transition: background 0.1s;
}

.dbg-item:hover {
  background: #f5f7fa;
}

.dbg-item.selected {
  background: #ecf5ff;
}

.dbg-item-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.dbg-event-tag {
  font-weight: 600;
}

.dbg-item-body {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #606266;
}

.dbg-model {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 140px;
}

.dbg-latency {
  color: #909399;
  flex-shrink: 0;
}

.dbg-item-time {
  font-size: 11px;
  color: #c0c4cc;
  margin-top: 2px;
}

.dbg-detail {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dbg-detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  border-bottom: 1px solid #e4e7ed;
  flex-shrink: 0;
}

.dbg-detail-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}

.dbg-detail-actions {
  display: flex;
  gap: 8px;
}

.dbg-detail-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dbg-meta {
  flex-shrink: 0;
}

.dbg-error {
  flex-shrink: 0;
}

.dbg-section {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;
}

.dbg-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #fafbfc;
  border-bottom: 1px solid #e4e7ed;
}

.dbg-section-title {
  font-size: 12px;
  font-weight: 600;
  color: #303133;
}

.dbg-code {
  margin: 0;
  padding: 12px;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow: auto;
  background: #272d32;
  color: #dce8eb;
}

.dbg-empty-detail {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
