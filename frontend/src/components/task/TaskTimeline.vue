<template>
  <div class="tl-wrapper">
    <div v-if="loading" v-loading="true" class="tl-loading" />
    <div v-else-if="error" class="tl-status">
      <el-empty :description="error" />
    </div>
    <div v-else-if="!events.length" class="tl-status">
      <el-empty description="暂无时间线事件" />
    </div>
    <div v-else class="tl-scroll">
      <div class="tl-list">
        <div
          v-for="event in events"
          :key="event.eventId"
          class="tl-item"
        >
          <div class="tl-dot" :style="{ background: phaseColor(event.phase) }" />
          <div class="tl-line" />
          <div class="tl-card" :style="{ borderLeftColor: phaseColor(event.phase) }">
            <div class="tl-card-header">
              <div class="tl-left">
                <span class="tl-phase-dot" :style="{ background: phaseColor(event.phase) }" />
                <span class="tl-phase-label">{{ phaseLabel(event.phase) }}</span>
                <span class="tl-event-type">{{ eventTypeLabel(event.eventType) }}</span>
              </div>
              <div class="tl-right">
                <span v-if="event.stepNumber > 0" class="tl-step">
                  <svg viewBox="0 0 16 16" fill="none" width="11" height="11"><circle
                    cx="8" cy="8" r="6"
                    stroke="currentColor"
                    stroke-width="1.2"
                  /><path
                    d="M8 5v3.5M8 11v.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"
                  /></svg>
                  步骤 {{ event.stepNumber }}
                </span>
                <span class="tl-time">{{ formatTime(event.createdAt) }}</span>
              </div>
            </div>
            <div class="tl-body">
              <p class="tl-summary">
                {{ event.summary }}
              </p>
              <div v-if="hasData(event.data)" class="tl-extras">
                <button class="tl-toggle" @click="toggleEvent(event.eventId)">
                  <svg
                    :class="['tl-chevron', { open: eventOpen(event.eventId) }]" viewBox="0 0 16 16" fill="none"
                    width="12" height="12"
                  >
                    <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                  </svg>
                  查看详情
                </button>
                <div v-if="eventOpen(event.eventId)" class="tl-extras-body">
                  <pre class="tl-code">{{ prettyJson(event.data) }}</pre>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import {onMounted, onUnmounted, ref} from "vue";
import {getTaskEvents} from "../../api";
import type {TaskEvent, TimelineEvent} from "../../types";
import {errorMessage} from "../../utils";

const props = defineProps<{
  taskId: string;
  onTaskEvent?: (cb: (event: TaskEvent) => void) => () => void;
}>();

const events = ref<TimelineEvent[]>([]);
const loading = ref(true);
const error = ref("");
const eventOpenMap = ref<Record<string, boolean>>({});

const PHASE_COLORS: Record<string, string> = {
  task: "#3b82f6",
  browser: "#10b981",
  planner: "#f59e0b",
  executor: "#6b8a9e",
  evaluator: "#ef4444",
  report: "#8b5cf6",
};

const PHASE_LABELS: Record<string, string> = {
  task: "任务",
  browser: "浏览器",
  planner: "规划器",
  executor: "执行器",
  evaluator: "评估器",
  report: "报告",
};

const EVENT_TYPE_LABELS: Record<string, string> = {
  start: "开始",
  open_url: "打开 URL",
  snapshot: "页面快照",
  planner_start: "规划开始",
  planner_result: "规划结果",
  action: "执行动作",
  evaluator_start: "评估开始",
  evaluator_result: "评估结果",
  report: "报告生成",
  complete: "完成",
  fail: "失败",
};

function phaseColor(phase: string): string {
  return PHASE_COLORS[phase] || "#909399";
}

function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] || phase;
}

function eventTypeLabel(eventType: string): string {
  return EVENT_TYPE_LABELS[eventType] || eventType;
}

function hasData(data: Record<string, unknown>): boolean {
  return data != null && typeof data === "object" && Object.keys(data).length > 0;
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

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function toggleEvent(id: string): void {
  eventOpenMap.value[id] = !eventOpenMap.value[id];
}

function eventOpen(id: string): boolean {
  return !!eventOpenMap.value[id];
}

function isTimelineEvent(raw: unknown): raw is TimelineEvent {
  if (!raw || typeof raw !== "object") return false;
  const r = raw as Record<string, unknown>;
  return typeof r.eventId === "string" && typeof r.taskId === "string";
}

onMounted(async () => {
  loading.value = true;
  error.value = "";
  try {
    events.value = await getTaskEvents(props.taskId);
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    loading.value = false;
  }

  if (props.onTaskEvent) {
    unregisterWs = props.onTaskEvent((wsEvent: TaskEvent) => {
      if (!wsEvent.eventType.startsWith("task.timeline.")) return;
      if (wsEvent.taskId !== props.taskId) return;
      const timelineEvent = wsEvent.data as unknown;
      if (!isTimelineEvent(timelineEvent)) return;
      if (!events.value.some(e => e.eventId === timelineEvent.eventId)) {
        events.value.push(timelineEvent);
      }
    });
  }
});

let unregisterWs: (() => void) | null = null;

onUnmounted(() => {
  unregisterWs?.();
});
</script>

<style scoped>
.tl-wrapper {
  flex: 1;
  min-height: 200px;
  display: flex;
  flex-direction: column;
}

.tl-loading {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}

.tl-status {
  padding: 48px 0;
}

.tl-scroll {
  flex: 1;
  overflow: auto;
}

/* ===== Timeline List ===== */
.tl-list {
  position: relative;
  padding: 12px 0 12px 24px;
}

/* ===== Item ===== */
.tl-item {
  position: relative;
  padding-left: 28px;
  padding-bottom: 20px;
}

.tl-item:last-child {
  padding-bottom: 0;
}

.tl-item:last-child .tl-line {
  display: none;
}

/* Dot */
.tl-dot {
  position: absolute;
  left: 0;
  top: 14px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  z-index: 2;
  border: 2px solid #fff;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.7), 0 4px 10px rgba(99, 102, 241, 0.18);
}

/* Line */
.tl-line {
  position: absolute;
  left: 6px;
  top: 28px;
  bottom: 0;
  width: 2px;
  background: linear-gradient(180deg, var(--brand-100, #e0e7ff) 0%, var(--line-soft, rgba(226, 232, 240, 0.7)) 100%);
}

/* ===== Card ===== */
.tl-card {
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid var(--line-soft, #e4e7ed);
  border-left: 3px solid var(--text-faint, #909399);
  border-radius: var(--radius-md, 14px);
  overflow: hidden;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  transition: box-shadow var(--transition-base, 0.22s cubic-bezier(0.4, 0, 0.2, 1)),
  transform var(--transition-base, 0.22s cubic-bezier(0.4, 0, 0.2, 1));
  box-shadow: var(--shadow-sm, 0 4px 12px rgba(15, 23, 42, 0.05));
}

.tl-card:hover {
  box-shadow: var(--shadow-md, 0 12px 28px rgba(15, 23, 42, 0.07));
  transform: translateY(-1px);
}

/* Card Header */
.tl-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.65) 0%, rgba(248, 250, 252, 0.45) 100%);
  border-bottom: 1px solid var(--line-soft, #e4e7ed);
  flex-wrap: wrap;
}

.tl-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tl-phase-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.7);
}

.tl-phase-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted, #4b5563);
  letter-spacing: 0.2px;
}

.tl-event-type {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-strong, #11181c);
}

.tl-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.tl-step {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--brand-600, #4f46e5);
  background: var(--brand-50, #f4f3ff);
  border: 1px solid var(--brand-100, #e0e7ff);
  padding: 2px 9px;
  border-radius: var(--radius-pill, 999px);
  white-space: nowrap;
  font-weight: 600;
}

.tl-time {
  font-size: 11px;
  color: var(--text-placeholder, #9ca3af);
  white-space: nowrap;
}

/* Card Body */
.tl-body {
  padding: 13px 14px;
  display: grid;
  gap: 9px;
}

.tl-summary {
  margin: 0;
  font-size: 13px;
  color: var(--text-base, #182125);
  line-height: 1.55;
}

/* Extras toggle */
.tl-extras {
  display: grid;
  gap: 6px;
}

.tl-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-xs, 6px);
  background: rgba(255, 255, 255, 0.6);
  color: var(--text-faint, #6b7280);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition-fast, 0.15s cubic-bezier(0.4, 0, 0.2, 1));
  font-family: inherit;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  width: 100%;
}

.tl-toggle:hover {
  background: var(--brand-50, #f4f3ff);
  color: var(--brand-600, #4f46e5);
  border-color: var(--brand-100, #e0e7ff);
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.12);
}

.tl-chevron {
  transition: transform var(--transition-fast, 0.15s cubic-bezier(0.4, 0, 0.2, 1));
}

.tl-chevron.open {
  transform: rotate(90deg);
}

.tl-extras-body {
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.tl-code {
  margin: 0;
  padding: 14px;
  border-radius: var(--radius-sm, 10px);
  background: #0f172a;
  color: #e2e8f0;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  line-height: 1.65;
  white-space: pre;
  max-height: 320px;
  overflow: auto;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
}
</style>
