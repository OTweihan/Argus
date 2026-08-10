<template>
  <div :class="['tl-wrapper', { 'is-whitebox-log': variant === 'whitebox-log' }]">
    <div v-if="loading" v-loading="true" class="tl-loading" />
    <div v-else-if="error" class="tl-status">
      <el-empty :description="error" />
    </div>
    <div v-else-if="!events.length" class="tl-status">
      <el-empty :description="variant === 'whitebox-log' ? '暂无分析日志' : '暂无时间线事件'" />
    </div>
    <div v-else-if="variant === 'whitebox-log'" class="build-log">
      <div class="build-log-toolbar">
        <div class="build-log-title">
          <span class="build-log-icon" aria-hidden="true">
            <svg viewBox="0 0 16 16">
              <path d="m3 4 2.5 2.5L3 9M7 10h6" />
            </svg>
          </span>
          <span>
            <strong>分析输出</strong>
            <small>Maven / Static Analysis</small>
          </span>
        </div>
        <span class="build-log-count">{{ events.length }} 条日志</span>
      </div>
      <div class="build-log-output">
        <button
          v-if="hasMoreEvents"
          class="load-more"
          @click="expandWindow"
        >
          ↑ 加载更早日志（{{ events.length - renderedEvents.length }} 条未显示）
        </button>
        <div
          v-for="event in renderedEvents"
          :key="event.eventId"
          :class="['build-log-entry', `is-${whiteboxLogLevel(event).toLowerCase()}`]"
        >
          <div class="build-log-line">
            <span class="build-log-time">{{ formatTime(event.createdAt) }}</span>
            <span class="build-log-level">{{ whiteboxLogLevel(event) }}</span>
            <span class="build-log-stage">[{{ whiteboxLogStage(event) }}]</span>
            <span class="build-log-message">{{
              event.summary || eventTypeLabel(event.eventType)
            }}</span>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="tl-scroll">
      <div class="tl-list">
        <button
          v-if="hasMoreEvents"
          class="load-more"
          @click="expandWindow"
        >
          ↑ 加载更早事件（{{ events.length - renderedEvents.length }} 条未显示）
        </button>
        <div v-for="event in renderedEvents" :key="event.eventId" class="tl-item">
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
                  <svg viewBox="0 0 16 16" fill="none" width="11" height="11">
                    <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.2" />
                    <path
                      d="M8 5v3.5M8 11v.5"
                      stroke="currentColor"
                      stroke-width="1.2"
                      stroke-linecap="round"
                    />
                  </svg>
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
                    :class="['tl-chevron', { open: eventOpen(event.eventId) }]"
                    viewBox="0 0 16 16"
                    fill="none"
                    width="12"
                    height="12"
                  >
                    <path
                      d="M6 4l4 4-4 4"
                      stroke="currentColor"
                      stroke-width="1.4"
                      stroke-linecap="round"
                    />
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
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { getTaskEvents } from "../../api";
import type { TaskEvent, TimelineEvent } from "../../types";
import { errorMessage } from "../../utils";
import {
  eventTypeLabel,
  formatTimelineTime as formatTime,
  hasTimelineData as hasData,
  isTimelineEvent,
  phaseColor,
  phaseLabel,
  prettyTimelineJson as prettyJson,
  whiteboxLogLevel,
  whiteboxLogStage,
} from "./timelineFormat";

const props = defineProps<{
  taskId: string;
  onTaskEvent?: (cb: (event: TaskEvent) => void) => () => void;
  variant?: "timeline" | "whitebox-log";
  /** 回放缺口/服务重启信号：值变化时从 SQLite 权威重拉时间线，补齐断线遗漏。 */
  reloadTick?: number;
}>();

const variant = props.variant ?? "timeline";

const events = ref<TimelineEvent[]>([]);
const loading = ref(true);
const error = ref("");
const eventOpenMap = ref<Record<string, boolean>>({});

// 长列表有界渲染：默认只渲染最近 RENDER_WINDOW 条，避免挂载拉全量 + 每个
// WS 事件追加时整列重渲染。白盒日志/时间线超过窗口时用"加载更早"按钮扩大窗口。
const RENDER_WINDOW_STEP = 200;
const renderWindow = ref(RENDER_WINDOW_STEP);
const renderedEvents = computed(() => events.value.slice(-renderWindow.value));
const hasMoreEvents = computed(() => events.value.length > renderedEvents.value.length);

function expandWindow(): void {
  renderWindow.value += RENDER_WINDOW_STEP;
}

function toggleEvent(id: string): void {
  eventOpenMap.value[id] = !eventOpenMap.value[id];
}

function eventOpen(id: string): boolean {
  return !!eventOpenMap.value[id];
}

onMounted(async () => {
  await loadEvents();

  if (props.onTaskEvent) {
    unregisterWs = props.onTaskEvent((wsEvent: TaskEvent) => {
      if (!wsEvent.eventType.startsWith("task.timeline.")) return;
      if (wsEvent.taskId !== props.taskId) return;
      const timelineEvent = wsEvent.data as unknown;
      if (!isTimelineEvent(timelineEvent)) return;
      if (!events.value.some((e) => e.eventId === timelineEvent.eventId)) {
        events.value.push(timelineEvent);
      }
    });
  }
});

let unregisterWs: (() => void) | null = null;

/** reloadTick 变化 → 权威重拉：清空后以 SQLite 为准重建，保留真实顺序。 */
watch(
  () => props.reloadTick,
  () => {
    if (props.reloadTick === undefined) return;
    void loadEvents();
  },
);

async function loadEvents(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    events.value = await getTaskEvents(props.taskId);
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    loading.value = false;
  }
}

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

.tl-wrapper.is-whitebox-log {
  min-height: 0;
  padding: 8px 8px 8px;
  overflow: hidden;
  box-sizing: border-box;
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

/* ===== Whitebox build log ===== */
.build-log {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-md, 14px);
  background: rgba(255, 255, 255, 0.88);
  box-shadow: var(--shadow-sm, 0 4px 12px rgba(15, 23, 42, 0.05));
}

.build-log-toolbar {
  min-height: 52px;
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  color: var(--text-faint, #6b7280);
  background: linear-gradient(180deg, #ffffff 0%, var(--surface-soft, #f8fafc) 100%);
  border-bottom: 1px solid var(--line-soft, #e4e7ed);
}

.build-log-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.build-log-title > span:last-child {
  display: grid;
  gap: 1px;
}

.build-log-title strong {
  color: var(--text-strong, #11181c);
  font-size: 13px;
  line-height: 1.35;
}

.build-log-title small {
  color: var(--text-placeholder, #9ca3af);
  font:
    10px/1.3 "Cascadia Code",
    "JetBrains Mono",
    Consolas,
    monospace;
  letter-spacing: 0.35px;
}

.build-log-icon {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 1px solid var(--brand-100, #cffaf8);
  border-radius: 9px;
  color: var(--brand-700, #087b78);
  background: var(--brand-50, #f4f3ff);
}

.build-log-icon svg {
  width: 17px;
  height: 17px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.build-log-count {
  padding: 3px 9px;
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-pill, 999px);
  color: var(--text-faint, #6b7280);
  background: rgba(255, 255, 255, 0.8);
  font-size: 12px;
}

.build-log-output {
  flex: 1;
  min-height: 0;
  padding: 6px 0;
  overflow: auto;
}

/* "加载更早"按钮：时间线与白盒日志共用 */
.load-more {
  display: block;
  width: 100%;
  margin: 10px auto 12px;
  padding: 8px 0;
  border: 1px dashed var(--line-soft, #e4e7ed);
  border-radius: var(--radius-xs, 6px);
  background: rgba(255, 255, 255, 0.55);
  color: var(--text-faint, #6b7280);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition-fast, 0.15s cubic-bezier(0.4, 0, 0.2, 1));
}

.load-more:hover {
  color: var(--brand-700, #087b78);
  border-color: var(--brand-100, #cffaf8);
  background: var(--brand-50, #f4f3ff);
}

.build-log-entry {
  border-left: 3px solid transparent;
  border-bottom: 1px solid rgba(226, 232, 240, 0.58);
}

.build-log-entry:last-child {
  border-bottom: 0;
}

.build-log-entry:hover {
  background: var(--brand-50, #f4f3ff);
}

.build-log-entry.is-success {
  border-left-color: #34d399;
}

.build-log-entry.is-warn {
  border-left-color: #fbbf24;
}

.build-log-entry.is-error {
  border-left-color: #fb7185;
}

.build-log-line {
  width: 100%;
  padding: 7px 14px 7px 11px;
  display: grid;
  grid-template-columns: 132px 64px 96px minmax(0, 1fr);
  align-items: baseline;
  gap: 10px;
  border: 0;
  color: var(--text-base, #182125);
  background: transparent;
  text-align: left;
  font:
    12px/1.65 "Cascadia Code",
    "JetBrains Mono",
    Consolas,
    monospace;
}

.build-log-time {
  color: var(--text-placeholder, #9ca3af);
}

.build-log-level {
  width: fit-content;
  padding: 1px 7px;
  border-radius: var(--radius-pill, 999px);
  color: #2563eb;
  background: #eff6ff;
  font-weight: 700;
}

.is-success .build-log-level {
  color: #047857;
  background: #ecfdf5;
}

.is-warn .build-log-level {
  color: #b45309;
  background: #fffbeb;
}

.is-error .build-log-level {
  color: #be123c;
  background: #fff1f2;
}

.build-log-stage {
  color: var(--brand-700, #087b78);
  font-weight: 650;
}

.build-log-message {
  min-width: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

@media (max-width: 860px) {
  .build-log-line {
    grid-template-columns: 1fr auto;
    gap: 2px 10px;
  }

  .build-log-time {
    grid-column: 1;
  }

  .build-log-level {
    grid-column: 2;
    grid-row: 1;
  }

  .build-log-stage,
  .build-log-message {
    grid-column: 1 / -1;
  }
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
  box-shadow:
    0 0 0 3px rgba(255, 255, 255, 0.7),
    0 4px 10px rgba(10, 186, 181, 0.18);
}

/* Line */
.tl-line {
  position: absolute;
  left: 6px;
  top: 28px;
  bottom: 0;
  width: 2px;
  background: linear-gradient(
    180deg,
    var(--brand-100, #cffaf8) 0%,
    var(--line-soft, rgba(226, 232, 240, 0.7)) 100%
  );
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
  transition:
    box-shadow var(--transition-base, 0.22s cubic-bezier(0.4, 0, 0.2, 1)),
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
  font-size: 13px;
  font-weight: 700;
  color: var(--text-muted, #4b5563);
  letter-spacing: 0.2px;
}

.tl-event-type {
  font-size: 14px;
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
  font-size: 13px;
  color: var(--brand-700, #087b78);
  background: var(--brand-50, #f4f3ff);
  border: 1px solid var(--brand-100, #cffaf8);
  padding: 2px 9px;
  border-radius: var(--radius-pill, 999px);
  white-space: nowrap;
  font-weight: 600;
}

.tl-time {
  font-size: 13px;
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
  font-size: 15px;
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
  font-size: 14px;
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
  color: var(--brand-700, #087b78);
  border-color: var(--brand-100, #cffaf8);
  box-shadow: 0 2px 6px rgba(10, 186, 181, 0.12);
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

.tl-code {
  margin: 0;
  padding: 14px;
  border-radius: var(--radius-sm, 10px);
  background: #0f172a;
  color: #e2e8f0;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 14px;
  line-height: 1.65;
  white-space: pre;
  max-height: 320px;
  overflow: auto;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
}
</style>
