<template>
  <div class="timeline-wrapper">
    <div v-if="loading" class="tl-loading" v-loading="true" />
    <div v-else-if="error" class="tl-error">
      <el-empty :description="error" />
    </div>
    <div v-else-if="!events.length" class="tl-empty">
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
          <div class="tl-card">
            <div class="tl-card-header">
              <div class="tl-left">
                <el-tag size="small" :color="phaseColor(event.phase)" class="tl-phase-tag">
                  {{ phaseLabel(event.phase) }}
                </el-tag>
                <span class="tl-event-type">{{ eventTypeLabel(event.eventType) }}</span>
              </div>
              <div class="tl-right">
                <span class="tl-step" v-if="event.stepNumber > 0">步骤 {{ event.stepNumber }}</span>
                <span class="tl-time">{{ formatTime(event.createdAt) }}</span>
              </div>
            </div>
            <div class="tl-body">
              <p class="tl-summary">{{ event.summary }}</p>
              <details v-if="hasData(event.data)" class="tl-details">
                <summary>查看详情</summary>
                <pre class="tl-json">{{ prettyJson(event.data) }}</pre>
              </details>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { getTaskEvents } from "../../api";
import type { TaskEvent, TimelineEvent } from "../../types";

const props = defineProps<{
  taskId: string;
  onTaskEvent?: (cb: (event: TaskEvent) => void) => () => void;
}>();

const events = ref<TimelineEvent[]>([]);
const loading = ref(true);
const error = ref("");

const PHASE_COLORS: Record<string, string> = {
  task: "#409EFF",
  browser: "#67C23A",
  planner: "#E6A23C",
  executor: "#909399",
  evaluator: "#F56C6C",
  report: "#9B59B6",
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
    error.value = caught instanceof Error ? caught.message : "加载时间线失败";
  } finally {
    loading.value = false;
  }

  /* ── 实时追加 WebSocket 时间线事件 ── */
  if (props.onTaskEvent) {
    unregisterWs = props.onTaskEvent((wsEvent: TaskEvent) => {
      const eventType = wsEvent.eventType ?? wsEvent.type ?? "";
      if (!eventType.startsWith("task.timeline.")) return;
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
.timeline-wrapper {
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

.tl-error,
.tl-empty {
  padding: 48px 0;
}

.tl-scroll {
  flex: 1;
  overflow: auto;
}

.tl-list {
  position: relative;
  padding: 8px 0 8px 20px;
}

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

.tl-dot {
  position: absolute;
  left: 0;
  top: 6px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  z-index: 1;
  border: 2px solid #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
}

.tl-line {
  position: absolute;
  left: 5px;
  top: 20px;
  bottom: 0;
  width: 2px;
  background: #e4e7ed;
}

.tl-card {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  transition: box-shadow 0.15s;
}

.tl-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.tl-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #fafbfc;
  border-bottom: 1px solid #f0f2f5;
  flex-wrap: wrap;
}

.tl-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tl-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.tl-phase-tag {
  --el-tag-text-color: #fff !important;
  border: none !important;
  font-weight: 600;
}

.tl-event-type {
  font-size: 12px;
  font-weight: 600;
  color: #303133;
}

.tl-step {
  font-size: 11px;
  color: #909399;
  background: #f0f2f5;
  padding: 1px 8px;
  border-radius: 4px;
  white-space: nowrap;
}

.tl-time {
  font-size: 11px;
  color: #909399;
  white-space: nowrap;
}

.tl-body {
  padding: 10px 14px;
}

.tl-summary {
  margin: 0;
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
}

.tl-details {
  margin-top: 8px;
  border: 1px solid #eef3f5;
  border-radius: 6px;
  padding: 8px 12px;
}

.tl-details[open] {
  padding-bottom: 12px;
}

.tl-details summary {
  cursor: pointer;
  color: #909399;
  font-size: 12px;
  font-weight: 600;
  user-select: none;
}

.tl-details summary:hover {
  color: #606266;
}

.tl-json {
  margin: 8px 0 0;
  padding: 10px;
  border-radius: 6px;
  background: #272d32;
  color: #dce8eb;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre;
  max-height: 300px;
  overflow: auto;
}
</style>
