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
        <div v-if="loadError" class="dbg-alert dbg-alert-error">
          <svg viewBox="0 0 20 20" fill="none" width="16" height="16"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4" /><path d="M10 6v4.5M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" /></svg>
          <span>{{ loadError }}</span>
        </div>
      </div>

      <!-- Right: detail -->
      <TraceDetailPanel v-if="selectedTrace" :trace="selectedTrace" />
      <el-empty v-else class="dbg-empty-detail" description="选择左侧追踪记录查看详情" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getTaskTraces, debugBundleUrl } from "../../api";
import type { LLMTraceRecord } from "../../types";
import { errorMessage } from "../../utils";
import TraceDetailPanel from "./debug/TraceDetailPanel.vue";

const props = defineProps<{ taskId: string }>();

const traces = ref<LLMTraceRecord[]>([]);
const loading = ref(true);
const loadError = ref("");
const selectedTrace = ref<LLMTraceRecord | null>(null);
const phaseFilter = ref("");
const hideStarted = ref(true);

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

function downloadDebugBundle() {
  window.open(debugBundleUrl(props.taskId), "_blank");
}

onMounted(async () => {
  loading.value = true;
  loadError.value = "";
  try {
    traces.value = await getTaskTraces(props.taskId);
  } catch (caught) {
    loadError.value = errorMessage(caught);
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

/* ===== Alert (list panel) ===== */
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

.dbg-empty-detail {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
