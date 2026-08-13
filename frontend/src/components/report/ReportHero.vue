<template>
  <header class="report-hero">
    <div class="hero-bg-grid" />
    <div class="hero-inner">
      <div class="hero-main">
        <div class="eyebrow">BLACKBOX TESTING</div>
        <h1>{{ taskName }}</h1>
        <p class="hero-desc">
          {{ summary }}
        </p>
        <div class="hero-status">
          <span :class="['status-badge', 'badge-' + status]">
            <span class="badge-dot" />
            {{ statusLabel }}
          </span>
          <span :class="['status-badge', findingCount === 0 ? 'badge-success' : 'badge-danger']">
            <svg viewBox="0 0 16 16" fill="none" width="12" height="12">
              <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.2" />
              <path
                d="M8 5v3.5M8 11v.5"
                stroke="currentColor"
                stroke-width="1.2"
                stroke-linecap="round"
              />
            </svg>
            问题 {{ findingCount }}
          </span>
          <span class="status-badge badge-info">
            <svg viewBox="0 0 16 16" fill="none" width="12" height="12">
              <path
                d="M2 4l6 3 6-3M2 12l6-3 6 3M2 8l6-3 6 3"
                stroke="currentColor"
                stroke-width="1.2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            步骤 {{ stepCount }} / {{ report.task.maxSteps }}
          </span>
        </div>
      </div>
      <aside class="hero-meta" aria-label="报告元信息">
        <div class="meta-row">
          <span class="meta-label">报告 ID</span>
          <span class="meta-value mono">{{ report.reportId }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">任务 ID</span>
          <span class="meta-value mono">{{ report.task.taskId }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">生成时间</span>
          <span class="meta-value">{{ formatReportDate(report.generatedAt) }}</span>
        </div>
      </aside>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { ReportData } from "../../types";
import { displayTaskName } from "../../utils";
import { formatReportDate } from "../task/report/reportUtils";

const props = defineProps<{
  report: ReportData;
  summary: string;
  status: string;
  statusLabel: string;
  findingCount: number;
  stepCount: number;
}>();

// 顶部大标题优先使用任务名（含重试次数）；旧报告缺失任务名时回落到固定标题。
const taskName = computed(() => {
  const { task } = props.report;
  return task.name?.trim() ? displayTaskName(task) : props.report.title;
});
</script>

<style scoped>
.report-hero {
  position: relative;
  width: min(1200px, 100%);
  margin: 0 auto;
  border: 1px solid rgba(10, 186, 181, 0.22);
  border-radius: var(--radius-lg, 18px);
  background:
    linear-gradient(120deg, rgba(255, 255, 255, 0.96), rgba(236, 254, 253, 0.88)),
    var(--surface-solid, #fff);
  box-shadow: var(--shadow-sm, 0 8px 24px rgba(15, 23, 42, 0.06));
  color: var(--text-strong, #172033);
  overflow: hidden;
}

.hero-bg-grid {
  position: absolute;
  inset: 0;
  background: transparent;
  pointer-events: none;
}

.report-hero::after {
  content: "";
  position: absolute;
  right: -88px;
  top: -132px;
  width: 220px;
  height: 220px;
  border-radius: 999px;
  background: rgba(10, 186, 181, 0.12);
  pointer-events: none;
}

.hero-inner {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 28px;
  padding: 22px 24px;
}

.hero-main {
  min-width: 0;
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 7px;
  color: var(--brand-700, #087b78);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.eyebrow::before {
  display: none;
}

.report-hero h1 {
  margin: 0;
  color: var(--text-strong, #172033);
  font-size: clamp(22px, 2.4vw, 30px);
  font-weight: 720;
  letter-spacing: -0.025em;
  line-height: 1.2;
}

.hero-desc {
  margin: 8px 0 0;
  color: var(--text-muted, #667085);
  font-size: 13px;
  line-height: 1.65;
  max-width: 760px;
}

.hero-status {
  margin-top: 14px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 76px;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.3;
  white-space: nowrap;
  background: rgba(255, 255, 255, 0.08);
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.16);
}

.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.badge-completed .badge-dot {
  background: #15803d;
}
.badge-failed .badge-dot,
.badge-timeout .badge-dot,
.badge-cancelled .badge-dot {
  background: #b42318;
}
.badge-running .badge-dot {
  background: #b54708;
}
.badge-pending .badge-dot {
  background: #175cd3;
}

.badge-completed,
.badge-success {
  background: #ecfdf3;
  color: #15803d;
  border-color: #bbf7d0;
}

.badge-failed,
.badge-cancelled,
.badge-danger {
  background: #fff1f3;
  color: #b42318;
  border-color: #fecdd3;
}

.badge-timeout {
  background: #fffaeb;
  color: #b54708;
  border-color: #fedf89;
}

.badge-running,
.badge-pending,
.badge-info {
  background: #eff8ff;
  color: #175cd3;
  border-color: #b2ddff;
}

.hero-meta {
  min-width: 300px;
  padding: 14px 16px;
  border: 1px solid var(--line-soft, #e4e7ec);
  border-radius: var(--radius-md, 14px);
  background: rgba(255, 255, 255, 0.7);
  display: grid;
  gap: 10px;
  align-content: start;
  box-shadow: var(--shadow-xs, 0 4px 14px rgba(15, 23, 42, 0.04));
  backdrop-filter: blur(12px);
}

.meta-row {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.meta-label {
  color: var(--text-faint, #98a2b3);
  font-size: 11px;
  font-weight: 700;
}

.meta-value {
  overflow-wrap: anywhere;
  color: var(--text-strong, #172033);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}

@media (max-width: 760px) {
  .hero-inner {
    grid-template-columns: 1fr;
    padding: 18px;
  }

  .hero-meta {
    min-width: 0;
  }
}
</style>
