<template>
  <div class="dbg-list-panel">
    <!-- Toolbar -->
    <div class="dbg-toolbar">
      <div class="dbg-toolbar-left">
        <div class="dbg-filter-group">
          <el-select
            :model-value="phaseFilter"
            placeholder="全部阶段"
            clearable
            style="width: 130px"
            @update:model-value="(v: string) => emit('update:phaseFilter', (v ?? '') as TracePhaseFilter)"
            @change="emit('filterChange')"
          >
            <el-option label="全部阶段" value="" />
            <el-option label="Planner" value="planner" />
            <el-option label="Evaluator" value="evaluator" />
          </el-select>
          <el-checkbox
            :model-value="hideStarted"
            label="隐藏 started"
            @update:model-value="(v: string | number | boolean) => emit('update:hideStarted', Boolean(v))"
            @change="emit('filterChange')"
          />
        </div>
        <span class="dbg-count">
          <svg viewBox="0 0 16 16" fill="none" width="12" height="12">
            <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.2" />
            <path d="M8 5v3.5M8 11v.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
          </svg>
          {{ traces.length }} 条追踪
        </span>
      </div>
      <div class="dbg-toolbar-right">
        <button class="dbg-dl-btn" @click="emit('download')">
          <svg viewBox="0 0 16 16" fill="none" width="13" height="13">
            <path d="M8 2v8M4 6l4 4 4-4M2 12v2h12v-2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          下载调试包
        </button>
      </div>
    </div>

    <!-- List -->
    <div class="dbg-list">
      <div
        v-for="trace in traces"
        :key="trace.traceId"
        :class="['dbg-item', { selected: selectedTraceId === trace.traceId }]"
        @click="emit('select', trace)"
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
      <el-empty v-if="!traces.length" :description="loading ? '加载中...' : '无追踪记录'" />
      <div v-if="loadError" class="dbg-alert dbg-alert-error">
        <svg viewBox="0 0 20 20" fill="none" width="16" height="16">
          <circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4" />
          <path d="M10 6v4.5M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
        <span>{{ loadError }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { LLMTraceRecord } from "../../../types";
import { eventLabel, eventTagType, formatTime } from "./traceFormat";
import type { TracePhaseFilter } from "./useTraceList";

defineProps<{
  traces: LLMTraceRecord[];
  loading: boolean;
  loadError: string;
  selectedTraceId: string | null;
  phaseFilter: TracePhaseFilter;
  hideStarted: boolean;
}>();

const emit = defineEmits<{
  (e: "select", trace: LLMTraceRecord): void;
  (e: "update:phaseFilter", value: TracePhaseFilter): void;
  (e: "update:hideStarted", value: boolean): void;
  (e: "filterChange"): void;
  (e: "download"): void;
}>();
</script>

<style scoped>
.dbg-list-panel {
  display: flex;
  flex-direction: column;
  min-width: 220px;
  width: 280px;
  flex-shrink: 0;
  border-right: 1px solid var(--line-soft, #e4e7ed);
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
  font-size: 14px;
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
  font-size: 14px;
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

/* ===== List ===== */
.dbg-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px 0;
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
  font-size: 12px;
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
  font-size: 12px;
  font-weight: 600;
}

.dbg-item-body {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
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
  font-size: 13px;
  font-weight: 600;
}

.dbg-item-time {
  font-size: 13px;
  color: var(--text-placeholder, #9ca3af);
}

/* ===== Alert (list panel) ===== */
.dbg-alert {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 14px;
  border-radius: var(--radius-sm, 10px);
  font-size: 15px;
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
</style>
