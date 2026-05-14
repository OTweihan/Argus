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
          <svg viewBox="0 0 16 16" fill="none" width="12" height="12"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.2" /><path d="M8 5v3.5M8 11v.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" /></svg>
          {{ filteredTraces.length }} 条追踪
        </span>
      </div>
      <div class="dbg-toolbar-right">
        <button class="dbg-dl-btn" @click="downloadDebugBundle">
          <svg viewBox="0 0 16 16" fill="none" width="13" height="13"><path d="M8 2v8M4 6l4 4 4-4M2 12v2h12v-2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" /></svg>
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
              <span v-if="trace.latencyMs != null && trace.latencyMs > 0" class="dbg-latency">
                {{ (trace.latencyMs / 1000).toFixed(1) }}s
              </span>
            </div>
            <div class="dbg-item-time">
              {{ formatTime(trace.timestamp) }}
            </div>
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
              <svg viewBox="0 0 16 16" fill="none" width="13" height="13"><rect x="5" y="2" width="10" height="11" rx="1.5" stroke="currentColor" stroke-width="1.3" /><path d="M2 5v8.5A1.5 1.5 0 003.5 15H11" stroke="currentColor" stroke-width="1.3" /></svg>
              复制 Prompt
            </button>
            <button class="dbg-copy-btn" @click="copyRawResponse">
              <svg viewBox="0 0 16 16" fill="none" width="13" height="13"><rect x="5" y="2" width="10" height="11" rx="1.5" stroke="currentColor" stroke-width="1.3" /><path d="M2 5v8.5A1.5 1.5 0 003.5 15H11" stroke="currentColor" stroke-width="1.3" /></svg>
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
            <div v-if="selectedTrace.latencyMs != null" class="dbg-meta-item">
              <span class="dbg-meta-label">耗时</span>
              <span class="dbg-meta-value">{{ (selectedTrace.latencyMs / 1000).toFixed(2) }}s</span>
            </div>
            <div class="dbg-meta-item">
              <span class="dbg-meta-label">时间</span>
              <span class="dbg-meta-value">{{ formatTime(selectedTrace.timestamp) }}</span>
            </div>
            <div v-if="tokenUsage?.prompt_tokens != null" class="dbg-meta-item">
              <span class="dbg-meta-label">Prompt Tokens</span>
              <span class="dbg-meta-value mono">{{ tokenUsage.prompt_tokens }}</span>
            </div>
            <div v-if="tokenUsage?.completion_tokens != null" class="dbg-meta-item">
              <span class="dbg-meta-label">Completion Tokens</span>
              <span class="dbg-meta-value mono">{{ tokenUsage.completion_tokens }}</span>
            </div>
          </div>

          <!-- Error banner -->
          <div v-if="selectedTrace.error" class="dbg-alert dbg-alert-error">
            <svg viewBox="0 0 20 20" fill="none" width="16" height="16"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4" /><path d="M10 6v4.5M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" /></svg>
            <span>{{ selectedTrace.error }}</span>
          </div>
          <div v-if="selectedTrace.parseError" class="dbg-alert dbg-alert-warning">
            <svg viewBox="0 0 20 20" fill="none" width="16" height="16"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4" /><path d="M10 6v4.5M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" /></svg>
            <span>解析失败：{{ selectedTrace.parseError }}</span>
          </div>

          <!-- Code sections -->
          <DebugCodeSection title="System Prompt" :content="systemPrompt" @copy="copyText" />
          <DebugCodeSection title="Input Payload" :content="inputPayloadStr" @copy="copyText" />
          <DebugCodeSection
            title="Raw Response"
            :content="selectedTrace.rawResponse ?? ''"
            @copy="copyText"
          />
          <DebugCodeSection title="Parsed Result" :content="parsedResultStr" @copy="copyText" />
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
import DebugCodeSection from "./debug/DebugCodeSection.vue";

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
  background: rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

/* ===== Toolbar ===== */
.dbg-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.7) 0%, rgba(248, 250, 252, 0.4) 100%);
  border-bottom: 1px solid var(--line-soft, #e4e7ed);
  flex-shrink: 0;
  gap: 12px;
  flex-wrap: wrap;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
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
  color: var(--text-faint, #6b7280);
  white-space: nowrap;
}

.dbg-toolbar-right {
  flex-shrink: 0;
}

.dbg-dl-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1px solid var(--brand-100, #e0e7ff);
  border-radius: var(--radius-sm, 10px);
  background: var(--brand-50, #f4f3ff);
  color: var(--brand-600, #4f46e5);
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all var(--transition-fast, 0.15s cubic-bezier(0.4, 0, 0.2, 1));
}

.dbg-dl-btn:hover {
  color: #ffffff;
  background-image: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  border-color: transparent;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.28);
  transform: translateY(-1px);
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
  border-right: 1px solid var(--line-soft, #e4e7ed);
  padding: 6px 0;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.dbg-item {
  display: flex;
  padding: 0;
  cursor: pointer;
  transition: background var(--transition-fast, 0.15s cubic-bezier(0.4, 0, 0.2, 1));
  border-bottom: 1px solid var(--line-soft, #e4e7ed);
  position: relative;
}

.dbg-item:hover {
  background: rgba(244, 243, 255, 0.6);
}

.dbg-item.selected {
  background: var(--brand-50, #f4f3ff);
  box-shadow: inset 0 0 0 1px rgba(99, 102, 241, 0.12);
}

.dbg-item.selected::before {
  content: "";
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background-image: linear-gradient(180deg, #6366f1 0%, #8b5cf6 100%);
}

.dbg-item-indicator {
  width: 3px;
  flex-shrink: 0;
}

.ind-success { background: linear-gradient(180deg, #10b981 0%, #059669 100%); }
.ind-danger { background: linear-gradient(180deg, #ef4444 0%, #dc2626 100%); }
.ind-warning { background: linear-gradient(180deg, #f59e0b 0%, #d97706 100%); }
.ind-info { background: linear-gradient(180deg, #94a3b8 0%, #64748b 100%); }

.dbg-item-content {
  flex: 1;
  padding: 10px 12px;
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
  padding: 0 9px;
  border-radius: var(--radius-pill, 999px);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.2px;
  border: 1px solid transparent;
}

.ev-success {
  background: var(--success-soft, #ecfdf5);
  color: var(--success, #15803d);
  border-color: #a7f3d0;
}

.ev-danger {
  background: var(--danger-soft, #fff1f2);
  color: var(--danger, #b42318);
  border-color: #fecdd3;
}

.ev-warning {
  background: var(--warning-soft, #fffaeb);
  color: var(--warning, #b54708);
  border-color: #fde68a;
}

.ev-info {
  background: var(--info-soft, #eff6ff);
  color: var(--info, #175cd3);
  border-color: #bfdbfe;
}

.dbg-phase-pill {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 8px;
  border-radius: var(--radius-xs, 6px);
  background: var(--brand-50, #f4f3ff);
  color: var(--brand-600, #4f46e5);
  border: 1px solid var(--brand-100, #e0e7ff);
  font-size: 10px;
  font-weight: 600;
}

.dbg-item-body {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-base, #182125);
}

.dbg-model {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 140px;
}

.dbg-latency {
  color: var(--text-faint, #6b7280);
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
}

.dbg-item-time {
  font-size: 11px;
  color: var(--text-placeholder, #9ca3af);
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
  padding: 11px 18px;
  border-bottom: 1px solid var(--line-soft, #e4e7ed);
  flex-shrink: 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.7) 0%, rgba(255, 255, 255, 0.4) 100%);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.dbg-detail-title {
  font-weight: 700;
  font-size: 14px;
  color: var(--text-strong, #11181c);
  letter-spacing: -0.005em;
}

.dbg-detail-actions {
  display: flex;
  gap: 6px;
}

.dbg-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-xs, 6px);
  background: rgba(255, 255, 255, 0.6);
  color: var(--text-muted, #4b5563);
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all var(--transition-fast, 0.15s cubic-bezier(0.4, 0, 0.2, 1));
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.dbg-copy-btn:hover {
  background: var(--brand-50, #f4f3ff);
  color: var(--brand-600, #4f46e5);
  border-color: var(--brand-100, #e0e7ff);
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.12);
}

.dbg-detail-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: transparent;
}

/* 关键：阻止 flex 容器压缩子项，否则 4 个 DebugCodeSection 会被压扁导致永远不溢出、滚不动 */
.dbg-detail-scroll > * {
  flex-shrink: 0;
}

/* ===== Meta Grid ===== */
.dbg-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1px;
  background: var(--line-soft, #e4e7ed);
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-sm, 10px);
  overflow: hidden;
  flex-shrink: 0;
  box-shadow: var(--shadow-xs, 0 1px 2px rgba(15, 23, 42, 0.04));
}

.dbg-meta-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 11px 14px;
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.dbg-meta-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-faint, #6b7280);
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.dbg-meta-value {
  font-size: 12px;
  color: var(--text-strong, #11181c);
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
  padding: 12px 14px;
  border-radius: var(--radius-sm, 10px);
  font-size: 13px;
  line-height: 1.4;
  flex-shrink: 0;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.dbg-alert svg {
  margin-top: 2px;
  flex-shrink: 0;
}

.dbg-alert-error {
  background: linear-gradient(135deg, rgba(255, 241, 242, 0.9) 0%, rgba(255, 255, 255, 0.7) 100%);
  border: 1px solid #fecdd3;
  color: var(--danger, #b42318);
}

.dbg-alert-warning {
  background: linear-gradient(135deg, rgba(255, 250, 235, 0.9) 0%, rgba(255, 255, 255, 0.7) 100%);
  border: 1px solid #fde68a;
  color: var(--warning, #b54708);
}

.dbg-empty-detail {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
