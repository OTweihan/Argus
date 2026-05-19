<template>
  <header class="report-hero">
    <div class="hero-bg-grid" />
    <div class="hero-inner">
      <div class="hero-main">
        <div class="eyebrow">
          Argus Blackbox Testing
        </div>
        <h1>{{ report.title }}</h1>
        <p class="hero-desc">{{ summary }}</p>
        <div class="hero-status">
          <span :class="['status-badge', 'badge-' + status]">
            <span class="badge-dot" />
            {{ statusLabel }}
          </span>
          <span :class="['status-badge', findingCount === 0 ? 'badge-success' : 'badge-danger']">
            <svg viewBox="0 0 16 16" fill="none" width="12" height="12"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.2" /><path d="M8 5v3.5M8 11v.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" /></svg>
            问题 {{ findingCount }}
          </span>
          <span class="status-badge badge-info">
            <svg viewBox="0 0 16 16" fill="none" width="12" height="12"><path d="M2 4l6 3 6-3M2 12l6-3 6 3M2 8l6-3 6 3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" /></svg>
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
          <span class="meta-value">{{ formatDate(report.generatedAt) }}</span>
        </div>
      </aside>
    </div>
  </header>
</template>

<script setup lang="ts">
import type { ReportData } from "../../types";
import { formatDate } from "../task/report/reportUtils";

defineProps<{
  report: ReportData;
  summary: string;
  status: string;
  statusLabel: string;
  findingCount: number;
  stepCount: number;
}>();
</script>

<style scoped>
.report-hero {
  position: relative;
  width: min(1200px, 100%);
  margin: 0 auto;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 28px;
  background:
      linear-gradient(135deg, rgba(23, 32, 51, 0.94), rgba(67, 56, 202, 0.92) 55%, rgba(124, 58, 237, 0.92)),
      #111827;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.08);
  color: #ffffff;
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
  right: -160px;
  top: -160px;
  width: 360px;
  height: 360px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
}

.hero-inner {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 28px;
  padding: 34px;
}

.hero-main {
  min-width: 0;
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  color: #c7d2fe;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.eyebrow::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #22c55e;
  box-shadow: 0 0 0 6px rgba(34, 197, 94, 0.18);
}

.report-hero h1 {
  margin: 0;
  color: #ffffff;
  font-size: clamp(28px, 4vw, 42px);
  font-weight: 740;
  letter-spacing: -0.04em;
  line-height: 1.25;
}

.hero-desc {
  margin: 12px 0 0;
  color: #dbe4ff;
  font-size: 15px;
  line-height: 1.65;
  max-width: 760px;
}

.hero-status {
  margin-top: 18px;
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

.badge-completed .badge-dot { background: #15803d; }
.badge-failed .badge-dot,
.badge-timeout .badge-dot,
.badge-cancelled .badge-dot { background: #b42318; }
.badge-running .badge-dot { background: #b54708; }
.badge-pending .badge-dot { background: #175cd3; }

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
  min-width: 290px;
  padding: 18px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.08);
  display: grid;
  gap: 10px;
  align-content: start;
  backdrop-filter: blur(16px);
}

.meta-row {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.meta-label {
  color: #c7d2fe;
  font-size: 12px;
}

.meta-value {
  overflow-wrap: anywhere;
  color: #ffffff;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}
</style>
