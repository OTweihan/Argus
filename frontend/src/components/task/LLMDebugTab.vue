<template>
  <div class="dbg-wrapper">
    <!-- Toolbar -->
    <div class="dbg-toolbar">
      <div class="dbg-toolbar-left">
        <div class="dbg-filter-group">
          <el-select v-model="phaseFilter" placeholder="全部阶段" clearable style="width: 130px" @change="onFilterChange">
            <el-option label="全部阶段" value="" />
            <el-option label="Planner" value="planner" />
            <el-option label="Evaluator" value="evaluator" />
          </el-select>
          <el-checkbox v-model="hideStarted" label="隐藏 started" @change="onFilterChange" />
        </div>
        <span class="dbg-count">
          <svg viewBox="0 0 16 16" fill="none" width="12" height="12"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.2"/><path d="M8 5v3.5M8 11v.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
          {{ filteredTraces.length }} 条追踪
        </span>
      </div>
      <div class="dbg-toolbar-right">
        <button class="dbg-dl-btn" @click="downloadDebugBundle">
          <svg viewBox="0 0 16 16" fill="none" width="13" height="13"><path d="M8 2v8M4 6l4 4 4-4M2 12v2h12v-2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
          下载调试包
        </button>
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
          <div class="dbg-item-indicator" :class="'ind-' + eventTagType(trace.event)" />
          <div class="dbg-item-content">
            <div class="dbg-item-header">
              <span :class="['dbg-event-tag', 'ev-' + eventTagType(trace.event)]">
                {{ eventLabel(trace.event) }}
              </span>
              <span class="dbg-phase-pill">{{ trace.phase }}</span>
            </div>
            <div class="dbg-item-body">
              <span class="dbg-model">{{ trace.model || '-' }}</span>
              <span class="dbg-latency" v-if="trace.latencyMs != null && trace.latencyMs > 0">
                {{ (trace.latencyMs / 1000).toFixed(1) }}s
              </span>
            </div>
            <div class="dbg-item-time">{{ formatTime(trace.timestamp) }}</div>
          </div>
        </div>
        <el-empty v-if="!filteredTraces.length" :description="loading ? '加载中...' : '无追踪记录'" />
      </div>

      <!-- Right: detail -->
      <div v-if="selectedTrace" class="dbg-detail">
        <div class="dbg-detail-header">
          <span class="dbg-detail-title">追踪详情</span>
          <div class="dbg-detail-actions">
            <button class="dbg-copy-btn" @click="copyPrompt">
              <svg viewBox="0 0 16 16" fill="none" width="13" height="13"><rect x="5" y="2" width="10" height="11" rx="1.5" stroke="currentColor" stroke-width="1.3"/><path d="M2 5v8.5A1.5 1.5 0 003.5 15H11" stroke="currentColor" stroke-width="1.3"/></svg>
              复制 Prompt
            </button>
            <button class="dbg-copy-btn" @click="copyRawResponse">
              <svg viewBox="0 0 16 16" fill="none" width="13" height="13"><rect x="5" y="2" width="10" height="11" rx="1.5" stroke="currentColor" stroke-width="1.3"/><path d="M2 5v8.5A1.5 1.5 0 003.5 15H11" stroke="currentColor" stroke-width="1.3"/></svg>
              复制 Raw Response
            </button>
          </div>
        </div>

        <div class="dbg-detail-scroll">
          <!-- Meta info -->
          <div class="dbg-meta-grid">
            <div class="dbg-meta-item">
              <span class="dbg-meta-label">阶段</span>
              <span class="dbg-meta-value">{{ selectedTrace.phase }}</span>
            </div>
            <div class="dbg-meta-item">
              <span class="dbg-meta-label">事件</span>
              <span class="dbg-meta-value">{{ eventLabel(selectedTrace.event) }}</span>
            </div>
            <div class="dbg-meta-item">
              <span class="dbg-meta-label">模型</span>
              <span class="dbg-meta-value mono">{{ selectedTrace.model || '-' }}</span>
            </div>
            <div class="dbg-meta-item">
              <span class="dbg-meta-label">Host</span>
              <span class="dbg-meta-value mono">{{ selectedTrace.baseUrlHost || '-' }}</span>
            </div>
            <div class="dbg-meta-item" v-if="selectedTrace.latencyMs != null">
              <span class="dbg-meta-label">耗时</span>
              <span class="dbg-meta-value">{{ (selectedTrace.latencyMs / 1000).toFixed(2) }}s</span>
            </div>
            <div class="dbg-meta-item">
              <span class="dbg-meta-label">时间</span>
              <span class="dbg-meta-value">{{ formatTime(selectedTrace.timestamp) }}</span>
            </div>
            <div class="dbg-meta-item" v-if="tokenUsage?.prompt_tokens != null">
              <span class="dbg-meta-label">Prompt Tokens</span>
              <span class="dbg-meta-value mono">{{ tokenUsage.prompt_tokens }}</span>
            </div>
            <div class="dbg-meta-item" v-if="tokenUsage?.completion_tokens != null">
              <span class="dbg-meta-label">Completion Tokens</span>
              <span class="dbg-meta-value mono">{{ tokenUsage.completion_tokens }}</span>
            </div>
          </div>

          <!-- Error banner -->
          <div v-if="selectedTrace.error" class="dbg-alert dbg-alert-error">
            <svg viewBox="0 0 20 20" fill="none" width="16" height="16"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4"/><path d="M10 6v4.5M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
            <span>{{ selectedTrace.error }}</span>
          </div>
          <div v-if="selectedTrace.parseError" class="dbg-alert dbg-alert-warning">
            <svg viewBox="0 0 20 20" fill="none" width="16" height="16"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4"/><path d="M10 6v4.5M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
            <span>解析失败：{{ selectedTrace.parseError }}</span>
          </div>

          <!-- Code sections -->
          <div v-if="systemPrompt" class="dbg-section">
            <div class="dbg-section-head" @click="toggleSection('sysprompt')">
              <span class="dbg-section-title">
                <svg :class="['dbg-sec-chevron', { open: sectionOpen('sysprompt') }]" viewBox="0 0 16 16" fill="none" width="11" height="11"><path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
                System Prompt
              </span>
              <button class="dbg-section-copy" @click.stop="copyText(systemPrompt)">复制</button>
            </div>
            <div v-if="sectionOpen('sysprompt')" class="dbg-section-body">
              <pre class="dbg-code">{{ systemPrompt }}</pre>
            </div>
          </div>

          <div v-if="inputPayloadStr" class="dbg-section">
            <div class="dbg-section-head" @click="toggleSection('payload')">
              <span class="dbg-section-title">
                <svg :class="['dbg-sec-chevron', { open: sectionOpen('payload') }]" viewBox="0 0 16 16" fill="none" width="11" height="11"><path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
                Input Payload
              </span>
              <button class="dbg-section-copy" @click.stop="copyText(inputPayloadStr)">复制</button>
            </div>
            <div v-if="sectionOpen('payload')" class="dbg-section-body">
              <pre class="dbg-code">{{ inputPayloadStr }}</pre>
            </div>
          </div>

          <div v-if="selectedTrace.rawResponse" class="dbg-section">
            <div class="dbg-section-head" @click="toggleSection('raw')">
              <span class="dbg-section-title">
                <svg :class="['dbg-sec-chevron', { open: sectionOpen('raw') }]" viewBox="0 0 16 16" fill="none" width="11" height="11"><path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
                Raw Response
              </span>
              <button class="dbg-section-copy" @click.stop="copyText(selectedTrace.rawResponse!)">复制</button>
            </div>
            <div v-if="sectionOpen('raw')" class="dbg-section-body">
              <pre class="dbg-code">{{ selectedTrace.rawResponse }}</pre>
            </div>
          </div>

          <div v-if="selectedTrace.parsedResult" class="dbg-section">
            <div class="dbg-section-head" @click="toggleSection('parsed')">
              <span class="dbg-section-title">
                <svg :class="['dbg-sec-chevron', { open: sectionOpen('parsed') }]" viewBox="0 0 16 16" fill="none" width="11" height="11"><path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
                Parsed Result
              </span>
              <button class="dbg-section-copy" @click.stop="copyText(parsedResultStr)">复制</button>
            </div>
            <div v-if="sectionOpen('parsed')" class="dbg-section-body">
              <pre class="dbg-code">{{ parsedResultStr }}</pre>
            </div>
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
const sectionsOpen = ref<Record<string, boolean>>({
  sysprompt: true,
  payload: true,
  raw: true,
  parsed: true,
});

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
  if (selectedTrace.value && !filteredTraces.value.includes(selectedTrace.value)) {
    selectedTrace.value = filteredTraces.value[0] || null;
  }
}

function toggleSection(key: string): void {
  sectionsOpen.value[key] = !sectionsOpen.value[key];
}

function sectionOpen(key: string): boolean {
  return sectionsOpen.value[key] !== false;
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

/* ===== Toolbar ===== */
.dbg-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 14px;
  background: #fafcfc;
  border-bottom: 1px solid #e6edf0;
  flex-shrink: 0;
  gap: 12px;
  flex-wrap: wrap;
}

.dbg-toolbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.dbg-filter-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dbg-count {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #687a85;
  white-space: nowrap;
}

.dbg-toolbar-right {
  flex-shrink: 0;
}

.dbg-dl-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid #dbe8fe;
  border-radius: 7px;
  background: #f0f6ff;
  color: #2563eb;
  font-size: 12px;
  font-weight: 550;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
}
.dbg-dl-btn:hover {
  background: #dbe8fe;
  border-color: #b8d2fb;
  box-shadow: 0 1px 3px rgba(37, 99, 235, 0.1);
}

/* ===== Main split ===== */
.dbg-main {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

/* ===== List ===== */
.dbg-list {
  width: 280px;
  min-width: 220px;
  overflow-y: auto;
  border-right: 1px solid #e6edf0;
  padding: 4px 0;
  flex-shrink: 0;
  background: #fafcfc;
}

.dbg-item {
  display: flex;
  padding: 0;
  cursor: pointer;
  transition: background 0.12s ease;
  border-bottom: 1px solid #f0f4f7;
  position: relative;
}
.dbg-item:hover {
  background: #f0f5f8;
}
.dbg-item.selected {
  background: #eef4ff;
}

.dbg-item-indicator {
  width: 3px;
  flex-shrink: 0;
}
.ind-success { background: #10b981; }
.ind-danger { background: #ef4444; }
.ind-warning { background: #f59e0b; }
.ind-info { background: #94a6b0; }

.dbg-item-content {
  flex: 1;
  padding: 9px 12px;
  display: grid;
  gap: 3px;
  min-width: 0;
}

.dbg-item-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dbg-event-tag {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.2px;
}

.ev-success { background: #ecfdf5; color: #059669; }
.ev-danger { background: #fef2f2; color: #dc2626; }
.ev-warning { background: #fffbeb; color: #d97706; }
.ev-info { background: #f0f4f7; color: #4b6572; }

.dbg-phase-pill {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 7px;
  border-radius: 4px;
  background: #eef4f7;
  color: #4b6572;
  font-size: 10px;
  font-weight: 550;
}

.dbg-item-body {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #374e5a;
}

.dbg-model {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 140px;
}

.dbg-latency {
  color: #687a85;
  flex-shrink: 0;
  font-size: 11px;
}

.dbg-item-time {
  font-size: 11px;
  color: #94a6b0;
}

/* ===== Detail ===== */
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
  border-bottom: 1px solid #e6edf0;
  flex-shrink: 0;
  background: #fff;
}

.dbg-detail-title {
  font-weight: 620;
  font-size: 14px;
  color: #1a2a32;
}

.dbg-detail-actions {
  display: flex;
  gap: 6px;
}

.dbg-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  border: 1px solid #e6edf0;
  border-radius: 6px;
  background: #fafcfd;
  color: #4b6572;
  font-size: 12px;
  font-weight: 540;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s ease;
}
.dbg-copy-btn:hover {
  background: #f0f4f7;
  color: #1a2a32;
  border-color: #d0dbdf;
}

.dbg-detail-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: #f8fafb;
}

/* ===== Meta Grid ===== */
.dbg-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1px;
  background: #e6edf0;
  border: 1px solid #e6edf0;
  border-radius: 8px;
  overflow: hidden;
  flex-shrink: 0;
}

.dbg-meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 14px;
  background: #ffffff;
}

.dbg-meta-label {
  font-size: 10px;
  font-weight: 600;
  color: #687a85;
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.dbg-meta-value {
  font-size: 12px;
  color: #1a2a32;
  word-break: break-word;
}

.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
}

/* ===== Alert ===== */
.dbg-alert {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.4;
  flex-shrink: 0;
}
.dbg-alert svg {
  margin-top: 2px;
  flex-shrink: 0;
}
.dbg-alert-error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}
.dbg-alert-warning {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
}

/* ===== Sections ===== */
.dbg-section {
  border: 1px solid #e6edf0;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 3px rgba(24, 40, 50, 0.04);
}

.dbg-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 9px 14px;
  background: #fafcfc;
  border-bottom: 1px solid #e6edf0;
  cursor: pointer;
  user-select: none;
  transition: background 0.12s ease;
}
.dbg-section-head:hover {
  background: #f0f4f7;
}

.dbg-section-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #1a2a32;
}

.dbg-sec-chevron {
  transition: transform 0.2s ease;
}
.dbg-sec-chevron.open {
  transform: rotate(90deg);
}

.dbg-section-copy {
  padding: 3px 10px;
  border: 1px solid #e6edf0;
  border-radius: 5px;
  background: #fff;
  color: #687a85;
  font-size: 11px;
  font-weight: 540;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.12s ease;
}
.dbg-section-copy:hover {
  background: #f0f4f7;
  color: #1a2a32;
  border-color: #d0dbdf;
}

.dbg-section-body {
  animation: fadeIn 0.18s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.dbg-code {
  margin: 0;
  padding: 14px;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow: auto;
  background: #1a2a32;
  color: #dce8eb;
}

.dbg-empty-detail {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
