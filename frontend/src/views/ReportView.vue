<template>
  <div v-if="loading" class="empty-state">
    <el-empty description="正在加载报告" />
  </div>
  <div v-else-if="!report" class="empty-state">
    <el-empty description="该任务尚未生成报告，请先执行任务。" />
  </div>
  <div v-else class="report-container">
    <!-- Hero -->
    <header class="report-hero">
      <div class="hero-bg-grid" />
      <div class="hero-inner">
        <div class="hero-main">
          <div class="eyebrow">
            <svg class="ei ei-shield" viewBox="0 0 16 16" fill="none" width="12" height="12">
              <path
                d="M8 1L2 3.5V7c0 4.2 2.7 7.5 6 8.5 3.3-1 6-4.3 6-8.5V3.5L8 1z" stroke="currentColor"
                stroke-width="1.2" fill="none"
              />
            </svg>
            Argus Blackbox Testing
          </div>
          <h1>{{ report.title }}</h1>
          <p class="hero-desc">
            {{ summary }}
          </p>
          <div class="hero-status">
            <span :class="['status-badge', 'badge-' + status]">
              <span class="badge-dot" />
              {{ statusLabel }}
            </span>
            <span class="status-badge" :class="findingCount === 0 ? 'badge-success' : 'badge-danger'">
              <svg viewBox="0 0 16 16" fill="none" width="12" height="12"><circle
                cx="8" cy="8" r="6"
                stroke="currentColor"
                stroke-width="1.2"
              /><path
                d="M8 5v3.5M8 11v.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"
              /></svg>
              问题 {{ findingCount }}
            </span>
            <span class="status-badge badge-info">
              <svg viewBox="0 0 16 16" fill="none" width="12" height="12"><path
                d="M2 4l6 3 6-3M2 12l6-3 6 3M2 8l6-3 6 3" stroke="currentColor" stroke-width="1.2"
                stroke-linecap="round" stroke-linejoin="round"
              /></svg>
              步骤 {{ stepCount }} / {{ report.task.max_steps }}
            </span>
          </div>
        </div>
        <aside class="hero-meta" aria-label="报告元信息">
          <div class="meta-row">
            <span class="meta-label">报告 ID</span>
            <span class="meta-value mono">{{ report.report_id }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">任务 ID</span>
            <span class="meta-value mono">{{ report.task.task_id }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">生成时间</span>
            <span class="meta-value">{{ formatDate(report.generated_at) }}</span>
          </div>
        </aside>
      </div>
    </header>

    <!-- Layout -->
    <div class="report-layout">
      <aside class="report-sidebar">
        <nav class="nav-card">
          <p class="nav-title">
            目录
          </p>
          <a
            v-for="item in navItems"
            :key="item.id"
            :class="['nav-link', { active: activeSection === item.id }]"
            :href="'#' + item.id"
            @click.prevent="scrollTo(item.id)"
          >
            <span class="nav-link-text">
              <span class="nav-index">{{ item.index }}</span>
              {{ item.label }}
            </span>
          </a>
        </nav>
      </aside>

      <main class="report-main">
        <!-- Overview / Metrics -->
        <section id="overview" class="section" data-section>
          <div class="metrics">
            <div class="r-metric metric-accent-info">
              <div class="metric-icon mi-info">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
                  <circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4" />
                  <path d="M10 7v5.5M10 5v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                </svg>
              </div>
              <div class="metric-body">
                <span class="metric-label">任务状态</span>
                <strong class="metric-value">{{ statusLabel }}</strong>
              </div>
            </div>
            <div class="r-metric metric-accent-primary">
              <div class="metric-icon mi-primary">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
                  <path d="M4 4h12v12H4z" stroke="currentColor" stroke-width="1.4" rx="2" />
                  <path d="M8 10l1.5 1.5L12 8.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                </svg>
              </div>
              <div class="metric-body">
                <span class="metric-label">展示步骤</span>
                <strong class="metric-value">{{ stepCount }}</strong>
              </div>
            </div>
            <div class="r-metric" :class="findingCount === 0 ? 'metric-accent-success' : 'metric-accent-danger'">
              <div class="metric-icon" :class="findingCount === 0 ? 'mi-success' : 'mi-danger'">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
                  <circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4" />
                  <path
                    v-if="findingCount === 0" d="M7 10l2 2 4-4" stroke="currentColor" stroke-width="1.4"
                    stroke-linecap="round"
                  />
                  <path v-else d="M10 7v4M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                </svg>
              </div>
              <div class="metric-body">
                <span class="metric-label">问题数量</span>
                <strong class="metric-value">{{ findingCount }}</strong>
              </div>
            </div>
            <div class="r-metric metric-accent-warning">
              <div class="metric-icon mi-warning">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
                  <path d="M10 3L3 17h14L10 3z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" />
                  <path d="M10 8v4M10 14v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                </svg>
              </div>
              <div class="metric-body">
                <span class="metric-label">失败步骤</span>
                <strong class="metric-value">{{ failedCount }}</strong>
              </div>
            </div>
            <div class="r-metric metric-accent-info">
              <div class="metric-icon mi-info">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
                  <path d="M2 10h4l2-5 4 10 2-5h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                </svg>
              </div>
              <div class="metric-body">
                <span class="metric-label">最大步数</span>
                <strong class="metric-value">{{ report.task.max_steps }}</strong>
              </div>
            </div>
          </div>
        </section>

        <!-- Task Info -->
        <section id="task" class="section section-card" data-section>
          <div class="section-head">
            <div class="section-title-group">
              <div class="section-icon">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
                  <rect x="3" y="3" width="14" height="14" rx="2" stroke="currentColor" stroke-width="1.4" />
                  <path d="M7 10l2 2 4-4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                </svg>
              </div>
              <div>
                <h2>任务信息</h2>
                <p class="section-subtitle">
                  记录测试目标、入口地址、执行结果与时间线。
                </p>
              </div>
            </div>
            <span :class="['status-badge', 'badge-' + status]">
              <span class="badge-dot" />
              {{ statusLabel }}
            </span>
          </div>
          <table class="info-table">
            <tbody>
              <tr>
                <th>任务 ID</th>
                <td><code>{{ report.task.task_id }}</code></td>
              </tr>
              <tr>
                <th>目标</th>
                <td>{{ report.task.goal }}</td>
              </tr>
              <tr>
                <th>起始 URL</th>
                <td>{{ report.task.start_url || '-' }}</td>
              </tr>
              <tr>
                <th>结果摘要</th>
                <td>{{ summary }}</td>
              </tr>
              <tr>
                <th>报告路径</th>
                <td><code>{{ report.task.report_path || '-' }}</code></td>
              </tr>
              <tr>
                <th>错误信息</th>
                <td>
                  <span v-if="report.task.error_message" class="error-text">{{ report.task.error_message }}</span>
                  <span v-else class="muted">无</span>
                </td>
              </tr>
              <tr>
                <th>创建时间</th>
                <td>{{ formatDate(report.task.created_at) }}</td>
              </tr>
              <tr>
                <th>开始时间</th>
                <td>{{ formatDate(report.task.started_at) }}</td>
              </tr>
              <tr>
                <th>完成时间</th>
                <td>{{ formatDate(report.task.completed_at) }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <!-- Steps -->
        <section id="steps" class="section" data-section>
          <div class="section-head">
            <div class="section-title-group">
              <div class="section-icon">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
                  <path
                    d="M4 10a1 1 0 112 0 1 1 0 01-2 0zM9 10a1 1 0 112 0 1 1 0 01-2 0zM14 10a1 1 0 112 0 1 1 0 01-2 0z"
                    stroke="currentColor" stroke-width="1.6"
                  />
                </svg>
              </div>
              <div>
                <h2>执行步骤</h2>
                <p class="section-subtitle">
                  按照 Agent 实际操作顺序展示关键动作。
                  <template v-if="report.hidden_steps_count > 0">
                    已隐藏 {{ report.hidden_steps_count }} 个内部等待或纯截图步骤。
                  </template>
                </p>
              </div>
            </div>
            <span :class="['status-badge', failedCount === 0 ? 'badge-success' : 'badge-danger']">
              失败 {{ failedCount }}
            </span>
          </div>

          <!-- Failed Steps Summary -->
          <div v-if="failedSteps.length" class="failure-summary">
            <div class="failure-summary-header">
              <svg viewBox="0 0 20 20" fill="none" width="16" height="16">
                <circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4" />
                <path d="M10 6v4.5M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
              </svg>
              <span>以下 {{ failedSteps.length }} 个步骤执行失败，点击可跳转查看详情</span>
            </div>
            <div class="failure-list">
              <a
                v-for="step in failedSteps"
                :key="step.step_number"
                :href="'#step-' + step.step_number"
                class="failure-chip"
                @click.prevent="scrollTo('step-' + step.step_number)"
              >
                <span class="failure-step-num">#{{ step.step_number }}</span>
                <span class="failure-msg">{{ step.error || step.message || '未记录错误详情' }}</span>
                <svg class="failure-arrow" viewBox="0 0 16 16" fill="none" width="12" height="12">
                  <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                </svg>
              </a>
            </div>
          </div>

          <!-- Timeline -->
          <div v-if="displaySteps.length" class="timeline">
            <div class="timeline-line" />
            <StepCard
              v-for="step in displaySteps"
              :key="step.task_log_id"
              :step="step"
              :task-id="taskId"
              @open-lightbox="openLightbox"
            />
          </div>
          <el-empty v-else description="暂无执行步骤" />
        </section>

        <!-- Findings -->
        <section id="findings" class="section section-card" data-section>
          <div class="section-head">
            <div class="section-title-group">
              <div class="section-icon">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
                  <path
                    d="M10 2l3 6 6 .5-4.5 4.5L16 19l-6-3-6 3 1.5-6L1 8.5 7 8l3-6z" stroke="currentColor"
                    stroke-width="1.4" stroke-linejoin="round"
                  />
                </svg>
              </div>
              <div>
                <h2>问题清单</h2>
                <p class="section-subtitle">
                  展示测试过程中识别到的缺陷、异常、风险或未完成目标。
                </p>
              </div>
            </div>
            <span :class="['status-badge', findingCount === 0 ? 'badge-success' : 'badge-danger']">
              {{ findingCount }} 个问题
            </span>
          </div>

          <div v-if="report.findings.length" class="findings-list">
            <FindingCard
              v-for="(finding, index) in report.findings"
              :key="finding.finding_id"
              :finding="finding"
              :index="index"
              :task-id="taskId"
              @open-lightbox="openLightbox"
            />
          </div>
          <el-empty v-else description="未记录问题" />
        </section>

        <!-- Raw JSON -->
        <section id="raw-json" class="section section-card" data-section>
          <div class="section-head">
            <div class="section-title-group">
              <div class="section-icon">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
                  <path
                    d="M5 7l-3 3 3 3M15 7l3 3-3 3M12 4l-4 12" stroke="currentColor" stroke-width="1.4"
                    stroke-linecap="round"
                  />
                </svg>
              </div>
              <div>
                <h2>原始 JSON</h2>
                <p class="section-subtitle">
                  完整结构化报告内容，可用于排查、归档或二次处理。
                </p>
              </div>
            </div>
          </div>
          <button class="extras-toggle" @click="rawJsonOpen = !rawJsonOpen">
            <svg :class="['chevron', { open: rawJsonOpen }]" viewBox="0 0 16 16" fill="none" width="12" height="12">
              <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
            </svg>
            {{ rawJsonOpen ? '收起' : '展开' }}原始 JSON
          </button>
          <div v-if="rawJsonOpen" class="extras-content">
            <pre class="code-block json-block">{{ reportJson }}</pre>
          </div>
        </section>
      </main>
    </div>

    <!-- Lightbox -->
    <Teleport to="body">
      <div v-if="lightboxSrc" class="lightbox-overlay" @click.self="closeLightbox">
        <button class="lightbox-close" @click="closeLightbox">
          <svg viewBox="0 0 20 20" fill="none" width="20" height="20">
            <path d="M5 5l10 10M15 5l-10 10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
          </svg>
        </button>
        <img class="lightbox-img" :src="screenshotSrc(lightboxSrc)" alt="截图全屏预览">
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import {computed, onMounted, onUnmounted, ref} from "vue";
import type {ReportData} from "../types";
import {screenshotUrl} from "../api";
import StepCard from "../components/task/report/StepCard.vue";
import FindingCard from "../components/task/report/FindingCard.vue";
import {formatDate, prettyJson} from "../components/task/report/reportUtils";

const props = defineProps<{
  report: ReportData | null;
  loading: boolean;
  taskId: string;
}>();

// --- reactive state ---
const activeSection = ref("");
const rawJsonOpen = ref(false);
const lightboxSrc = ref<string | null>(null);
const observer = ref<IntersectionObserver | null>(null);

// --- nav items ---
const navItems = [
  {id: "overview", label: "概览", index: "01"},
  {id: "task", label: "任务信息", index: "02"},
  {id: "steps", label: "执行步骤", index: "03"},
  {id: "findings", label: "问题清单", index: "04"},
  {id: "raw-json", label: "原始 JSON", index: "05"},
];

// --- computed ---
const status = computed(() => props.report?.task?.status ?? "");
const statusLabel = computed(() => {
  const map: Record<string, string> = {
    completed: "已完成", failed: "失败", timeout: "超时",
    cancelled: "已取消", running: "运行中", pending: "等待中",
  };
  return map[status.value] || status.value;
});
const summary = computed(() => props.report?.summary || props.report?.task?.result_summary || "未记录结果摘要。");
const displaySteps = computed(() => props.report?.display_steps ?? []);
const failedSteps = computed(() => displaySteps.value.filter((s) => s.result === "failed"));
const failedCount = computed(() => failedSteps.value.length);
const findingCount = computed(() => props.report?.findings?.length ?? 0);
const stepCount = computed(() => displaySteps.value.length);
const reportJson = computed(() => prettyJson(props.report));

// --- functions ---
function screenshotSrc(path: string): string {
  return screenshotUrl(props.taskId, path);
}

function scrollTo(id: string): void {
  const el = document.getElementById(id);
  if (el) {
    el.scrollIntoView({behavior: "smooth", block: "start"});
  }
}

function openLightbox(path: string): void {
  lightboxSrc.value = path;
}

function closeLightbox(): void {
  lightboxSrc.value = null;
}

// --- scroll spy ---
onMounted(() => {
  const sections = document.querySelectorAll("[data-section]");
  if (!sections.length) return;
  observer.value = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            activeSection.value = entry.target.id;
          }
        }
      },
      {rootMargin: "-80px 0px -60% 0px"}
  );
  sections.forEach((s) => observer.value!.observe(s));
  activeSection.value = sections[0].id;
});

onUnmounted(() => {
  observer.value?.disconnect();
});
</script>

<style scoped>
/* ===== Variables ===== */
.report-container {
  --rp-bg: #f3f6fb;
  --rp-surface: #ffffff;
  --rp-surface-soft: #f8fafc;
  --rp-line: #e4e7ec;
  --rp-line-light: #e4e7ec;
  --rp-line-strong: #d0d5dd;
  --rp-text: #172033;
  --rp-muted: #667085;
  --rp-muted-light: #98a2b3;
  --radius: 20px;
  --radius-md: 14px;
  --radius-sm: 10px;
  --shadow-sm: 0 10px 32px rgba(15, 23, 42, 0.05);
  --shadow-md: 0 12px 30px rgba(15, 23, 42, 0.06);
  --shadow-lg: 0 14px 40px rgba(15, 23, 42, 0.08);
  --transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  /* 与全局令牌对齐，保持色板一致 */
  --accent: var(--brand-600, #4f46e5);
  --accent-soft: var(--brand-50, #eef2ff);
  --success: #15803d;
  --success-soft: #ecfdf3;
  --danger: #b42318;
  --danger-soft: #fff1f3;
  --warning: #b54708;
  --warning-soft: #fffaeb;
  --info: #175cd3;
  --info-soft: #eff8ff;
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 28px 20px 44px;
  background: transparent;
  scroll-behavior: smooth;
}

/* ===== Hero ===== */
.report-hero {
  position: relative;
  width: min(1200px, 100%);
  margin: 0 auto;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 28px;
  background:
      linear-gradient(135deg, rgba(23, 32, 51, 0.94), rgba(67, 56, 202, 0.92) 55%, rgba(124, 58, 237, 0.92)),
      #111827;
  box-shadow: var(--shadow-lg);
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

.eyebrow svg {
  display: none;
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

/* Status Badges */
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
  background: var(--success);
}

.badge-failed .badge-dot,
.badge-timeout .badge-dot,
.badge-cancelled .badge-dot {
  background: var(--danger);
}

.badge-running .badge-dot {
  background: var(--warning);
  animation: pulse-dot 1.5s ease infinite;
}

.badge-pending .badge-dot {
  background: var(--info);
}

.badge-completed,
.badge-success {
  background: var(--success-soft);
  color: var(--success);
  border-color: #bbf7d0;
}

.badge-failed,
.badge-cancelled,
.badge-danger {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: #fecdd3;
}

.badge-timeout {
  background: var(--warning-soft);
  color: var(--warning);
  border-color: #fedf89;
}

.badge-running,
.badge-pending,
.badge-info {
  background: var(--info-soft);
  color: var(--info);
  border-color: #b2ddff;
}

@keyframes pulse-dot {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
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

/* ===== Layout ===== */
.report-layout {
  width: min(1200px, 100%);
  margin: 0 auto;
  padding: 22px 0 0;
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 22px;
  align-items: start;
}

.report-sidebar {
  position: sticky;
  top: 18px;
}

/* Nav */
.nav-card {
  border: 1px solid var(--rp-line);
  border-radius: var(--radius);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: var(--shadow-sm);
  padding: 14px;
  display: grid;
  gap: 0;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
}

.nav-title {
  margin: 0 0 10px;
  color: var(--rp-muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.nav-link {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 11px;
  color: #344054;
  text-decoration: none;
  transition: all var(--transition);
}

.nav-link:hover {
  background: var(--accent-soft);
  color: var(--accent);
  transform: translateX(2px);
}

.nav-link.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
  box-shadow: inset 0 0 0 1px rgba(99, 102, 241, 0.10);
}

.nav-link.active::before {
  content: "";
  position: absolute;
  left: -14px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 18px;
  border-radius: 0 3px 3px 0;
  background-image: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.45);
}

.nav-link-text {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}

.nav-index {
  order: 2;
  margin-left: auto;
  font-size: 12px;
  font-weight: 500;
  color: inherit;
  opacity: 0.55;
}

.nav-link.active .nav-index {
  opacity: 0.8;
}

/* ===== Main ===== */
.report-main {
  min-width: 0;
  display: grid;
  gap: 18px;
}

.section {
  display: grid;
  gap: 14px;
  scroll-margin-top: 20px;
}

.section-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
}

.section-title-group {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.section-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background-image: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  color: var(--accent);
  flex-shrink: 0;
  margin-top: 1px;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.15), inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

.section-head h2 {
  margin: 0;
  color: var(--rp-text);
  font-size: 21px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.25;
}

.section-subtitle {
  margin: 5px 0 0;
  color: var(--rp-muted);
  font-size: 14px;
  line-height: 1.5;
}

/* ===== Section Card ===== */
.section-card {
  border: 1px solid var(--rp-line);
  border-radius: var(--radius);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: var(--shadow-sm);
  padding: 22px;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  transition: box-shadow var(--transition), transform var(--transition);
}

.section-card:hover {
  box-shadow: var(--shadow-md);
}

/* ===== Metrics ===== */
.metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
  margin-top: -10px;
}

.r-metric {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 14px;
  border: 1px solid var(--rp-line);
  border-radius: var(--radius);
  background: rgba(255, 255, 255, 0.78);
  padding: 20px;
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  transition: box-shadow var(--transition), transform var(--transition);
}

.r-metric::after {
  content: "";
  position: absolute;
  right: -28px;
  bottom: -28px;
  width: 96px;
  height: 96px;
  border-radius: 999px;
  background: var(--accent-soft);
  filter: blur(2px);
  opacity: 0.85;
  pointer-events: none;
  transition: transform var(--transition);
}

.r-metric:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.r-metric:hover::after {
  transform: scale(1.08);
}

.metric-accent-success::after {
  background: var(--success-soft);
}

.metric-accent-danger::after {
  background: var(--danger-soft);
}

.metric-accent-warning::after {
  background: var(--warning-soft);
}

.metric-accent-info::after {
  background: var(--info-soft);
}

.metric-icon {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  flex-shrink: 0;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

.mi-primary {
  background: var(--accent-soft);
  color: var(--accent);
}

.mi-success {
  background: var(--success-soft);
  color: var(--success);
}

.mi-danger {
  background: var(--danger-soft);
  color: var(--danger);
}

.mi-warning {
  background: var(--warning-soft);
  color: var(--warning);
}

.mi-info {
  background: var(--info-soft);
  color: var(--info);
}

.metric-body {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 6px;
  min-width: 0;
}

.metric-label {
  font-size: 12px;
  color: var(--rp-muted);
  font-weight: 600;
  white-space: nowrap;
}

.metric-value {
  font-size: 26px;
  font-weight: 720;
  color: var(--rp-text);
  letter-spacing: -0.04em;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ===== Info Table ===== */
.info-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  overflow: hidden;
  border: 1px solid var(--rp-line);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.55);
  margin-top: 4px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.info-table th, .info-table td {
  padding: 13px 16px;
  text-align: left;
  vertical-align: top;
  font-size: 14px;
}

.info-table tr:not(:last-child) th,
.info-table tr:not(:last-child) td {
  border-bottom: 1px solid var(--rp-line);
}

.info-table th {
  width: 150px;
  background: rgba(248, 250, 252, 0.7);
  color: var(--rp-muted);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: none;
  white-space: nowrap;
}

.info-table td {
  color: var(--rp-text);
  overflow-wrap: anywhere;
}

.info-table code, code {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
  background: #f2f4f7;
  padding: 2px 6px;
  border: 1px solid var(--rp-line);
  border-radius: 7px;
  color: #344054;
}

/* ===== Timeline ===== */
.timeline {
  position: relative;
  display: grid;
  gap: 14px;
  padding-left: 52px;
}

.timeline-line {
  position: absolute;
  left: 24px;
  top: 18px;
  bottom: 18px;
  width: 2px;
  background: linear-gradient(180deg, var(--accent), rgba(79, 70, 229, 0.08));
  border-radius: 1px;
}

/* step-card / step-node / step-detail-grid 等已迁至 components/task/report/StepCard.vue。 */

/* ===== Extras / Toggles ===== */
.extras-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid var(--rp-line);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.6);
  color: var(--rp-muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition);
  font-family: inherit;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.extras-toggle:hover {
  background: var(--accent-soft);
  color: var(--accent);
  border-color: #c7d2fe;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.12);
}

.chevron {
  transition: transform var(--transition);
}

.chevron.open {
  transform: rotate(90deg);
}

.extras-content {
  margin-top: 10px;
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

.code-block {
  margin: 0;
  padding: 13px;
  border-radius: var(--radius-md);
  background: #0f172a;
  color: #e2e8f0;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
  line-height: 1.7;
  overflow-x: auto;
  white-space: pre-wrap;
}

.json-block {
  max-height: 520px;
  overflow: auto;
}

/* screenshot / screenshot-path 已迁至子组件；ReportView 自身不直接渲染截图。 */

/* ===== Failure Summary ===== */
.failure-summary {
  border: 1px solid #fecdd3;
  border-radius: var(--radius);
  background:
      linear-gradient(135deg, rgba(255, 241, 242, 0.9) 0%, rgba(255, 255, 255, 0.78) 60%);
  padding: 20px;
  box-shadow: 0 8px 24px rgba(180, 35, 24, 0.08);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
}

.failure-summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--danger);
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 12px;
}

.failure-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.failure-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid #fecdd3;
  text-decoration: none;
  color: var(--rp-text);
  font-size: 13px;
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  transition: all var(--transition);
}

.failure-chip:hover {
  background: var(--danger-soft);
  border-color: #fecaca;
  box-shadow: 0 6px 16px rgba(180, 35, 24, 0.12);
  transform: translateX(2px);
}

.failure-step-num {
  font-weight: 700;
  color: var(--danger);
  flex-shrink: 0;
  font-size: 13px;
}

.failure-msg {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.failure-arrow {
  color: var(--rp-muted);
  flex-shrink: 0;
}

/* ===== Findings ===== */
.findings-list {
  position: relative;
  display: grid;
  gap: 14px;
}

/* finding-card / sev-tag-* / finding-meta-grid 等已迁至 components/task/report/FindingCard.vue。 */

/* ===== Lightbox ===== */
.lightbox-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(15, 23, 42, 0.88);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px;
  cursor: zoom-out;
  animation: fadeIn 0.2s ease;
}

.lightbox-close {
  position: absolute;
  top: 16px;
  right: 16px;
  background: #ffffff;
  border: 0;
  color: #111827;
  width: 40px;
  height: 40px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background var(--transition);
}

.lightbox-close:hover {
  background: #eef2ff;
}

.lightbox-img {
  max-width: min(96vw, 1440px);
  max-height: 86vh;
  border: 1px solid #ffffff;
  border-radius: var(--radius-md);
  background: #ffffff;
  object-fit: contain;
}

/* ===== Utility ===== */
.muted {
  color: var(--rp-muted);
}

.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}

.error-text {
  color: var(--danger);
}

.url-text {
  color: var(--accent);
  word-break: break-all;
}

/* ===== Empty States ===== */
.empty-state {
  text-align: center;
  padding: 48px 24px;
}

/* ===== Responsive ===== */
@media (max-width: 1024px) {
  .hero-inner {
    grid-template-columns: 1fr;
  }

  .report-layout {
    grid-template-columns: 1fr;
  }

  .report-sidebar {
    position: static;
  }

  .nav-card {
    display: none;
  }

  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .report-container {
    padding: 12px 12px 32px;
  }

  .hero-inner {
    padding: 22px;
  }

  .hero-meta {
    min-width: 0;
  }

  .metrics {
    grid-template-columns: 1fr;
  }

  .section-head {
    display: grid;
  }

  .info-table,
  .info-table tbody,
  .info-table tr,
  .info-table th,
  .info-table td {
    display: block;
    width: 100%;
  }

  .info-table th {
    border-bottom: 0 !important;
  }

  .timeline {
    padding-left: 42px;
  }

  .timeline-line {
    left: 17px;
  }

  .section-card {
    padding: 20px;
  }
}
</style>
