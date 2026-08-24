<template>
  <div class="build-log">
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
      <span class="build-log-count">{{ total }} 条日志</span>
    </div>
    <div class="build-log-output">
      <button v-if="hasMore" class="load-more" @click="$emit('load-more')">
        ↑ 加载更早日志（{{ hiddenCount }} 条未显示）
      </button>
      <div
        v-for="event in events"
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
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { TimelineEvent } from "../../../types";
import {
  eventTypeLabel,
  formatTimelineTime as formatTime,
  whiteboxLogLevel,
  whiteboxLogStage,
} from "../timelineFormat";

const props = defineProps<{
  /** 当前窗口内渲染的事件（有界渲染由父级 TaskTimeline 管理）。 */
  events: TimelineEvent[];
  /** 全量事件条数，用于总数徽标与「加载更早」可见性。 */
  total: number;
}>();

defineEmits<{
  "load-more": [];
}>();

const hiddenCount = computed(() => Math.max(0, props.total - props.events.length));
const hasMore = computed(() => hiddenCount.value > 0);
</script>

<style scoped>
/* ===== Whitebox build log =====
 * 「加载更早」按钮样式与 TaskTimeline 时间线分支共用，各自 scoped 持有一份。 */
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
</style>
