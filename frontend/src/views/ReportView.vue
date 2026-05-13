<template>
  <div v-if="loading" class="empty-state">
    <el-empty description="正在加载报告"/>
  </div>
  <div v-else-if="!report" class="empty-state">
    <el-empty description="该任务尚未生成报告，请先执行任务。"/>
  </div>
  <div v-else class="report-container">
    <!-- Hero -->
    <header class="report-hero">
      <div class="hero-bg-grid"/>
      <div class="hero-inner">
        <div class="hero-main">
          <div class="eyebrow">
            <svg class="ei ei-shield" viewBox="0 0 16 16" fill="none" width="12" height="12"><path d="M8 1L2 3.5V7c0 4.2 2.7 7.5 6 8.5 3.3-1 6-4.3 6-8.5V3.5L8 1z" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
            Argus Blackbox Testing
          </div>
          <h1>{{ report.title }}</h1>
          <p class="hero-desc">{{ summary }}</p>
          <div class="hero-status">
            <span :class="['status-badge', 'badge-' + status]">
              <span class="badge-dot"/>
              {{ statusLabel }}
            </span>
            <span class="status-badge" :class="findingCount === 0 ? 'badge-success' : 'badge-danger'">
              <svg viewBox="0 0 16 16" fill="none" width="12" height="12"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.2"/><path d="M8 5v3.5M8 11v.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
              问题 {{ findingCount }}
            </span>
            <span class="status-badge badge-info">
              <svg viewBox="0 0 16 16" fill="none" width="12" height="12"><path d="M2 4l6 3 6-3M2 12l6-3 6 3M2 8l6-3 6 3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
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
          <p class="nav-title">目录</p>
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
        <section class="section" id="overview" data-section>
          <div class="metrics">
            <div class="r-metric metric-accent-info">
              <div class="metric-icon mi-info">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4"/><path d="M10 7v5.5M10 5v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
              </div>
              <div class="metric-body">
                <span class="metric-label">任务状态</span>
                <strong class="metric-value">{{ statusLabel }}</strong>
              </div>
            </div>
            <div class="r-metric metric-accent-primary">
              <div class="metric-icon mi-primary">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M4 4h12v12H4z" stroke="currentColor" stroke-width="1.4" rx="2"/><path d="M8 10l1.5 1.5L12 8.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
              </div>
              <div class="metric-body">
                <span class="metric-label">展示步骤</span>
                <strong class="metric-value">{{ stepCount }}</strong>
              </div>
            </div>
            <div class="r-metric" :class="findingCount === 0 ? 'metric-accent-success' : 'metric-accent-danger'">
              <div class="metric-icon" :class="findingCount === 0 ? 'mi-success' : 'mi-danger'">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4"/><path d="M7 10l2 2 4-4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" v-if="findingCount === 0"/><path d="M10 7v4M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" v-else/></svg>
              </div>
              <div class="metric-body">
                <span class="metric-label">问题数量</span>
                <strong class="metric-value">{{ findingCount }}</strong>
              </div>
            </div>
            <div class="r-metric metric-accent-warning">
              <div class="metric-icon mi-warning">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M10 3L3 17h14L10 3z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M10 8v4M10 14v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
              </div>
              <div class="metric-body">
                <span class="metric-label">失败步骤</span>
                <strong class="metric-value">{{ failedCount }}</strong>
              </div>
            </div>
            <div class="r-metric metric-accent-info">
              <div class="metric-icon mi-info">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M2 10h4l2-5 4 10 2-5h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
              </div>
              <div class="metric-body">
                <span class="metric-label">最大步数</span>
                <strong class="metric-value">{{ report.task.max_steps }}</strong>
              </div>
            </div>
          </div>
        </section>

        <!-- Task Info -->
        <section class="section section-card" id="task" data-section>
          <div class="section-head">
            <div class="section-title-group">
              <div class="section-icon">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18"><rect x="3" y="3" width="14" height="14" rx="2" stroke="currentColor" stroke-width="1.4"/><path d="M7 10l2 2 4-4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
              </div>
              <div>
                <h2>任务信息</h2>
                <p class="section-subtitle">记录测试目标、入口地址、执行结果与时间线。</p>
              </div>
            </div>
            <span :class="['status-badge', 'badge-' + status]">
              <span class="badge-dot"/>
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
        <section class="section" id="steps" data-section>
          <div class="section-head">
            <div class="section-title-group">
              <div class="section-icon">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M4 10a1 1 0 112 0 1 1 0 01-2 0zM9 10a1 1 0 112 0 1 1 0 01-2 0zM14 10a1 1 0 112 0 1 1 0 01-2 0z" stroke="currentColor" stroke-width="1.6"/></svg>
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
              <svg viewBox="0 0 20 20" fill="none" width="16" height="16"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4"/><path d="M10 6v4.5M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
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
                <svg class="failure-arrow" viewBox="0 0 16 16" fill="none" width="12" height="12"><path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
              </a>
            </div>
          </div>

          <!-- Timeline -->
          <div v-if="displaySteps.length" class="timeline">
            <div class="timeline-line"/>
            <article
              v-for="step in displaySteps"
              :key="step.task_log_id"
              :id="'step-' + step.step_number"
              :class="['step-card', 'step-' + step.result]"
            >
              <div class="step-node" :class="'node-' + step.result">
                <template v-if="step.result === 'success'">
                  <svg viewBox="0 0 16 16" fill="none" width="10" height="10"><path d="M4 8l3 3 5-5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
                </template>
                <template v-else-if="step.result === 'failed'">
                  <svg viewBox="0 0 16 16" fill="none" width="10" height="10"><path d="M5 5l6 6M11 5l-6 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
                </template>
                <template v-else>
                  <span>{{ step.step_number }}</span>
                </template>
              </div>
              <div class="step-card-body">
                <div class="step-header">
                  <div class="step-title-row">
                    <h3 class="step-title">{{ step.message || step.action }}</h3>
                    <span class="step-pill">{{ step.action }}</span>
                  </div>
                  <span :class="['step-result-tag', 'tag-' + step.result]">{{ step.result }}</span>
                </div>

                <div class="step-detail-grid">
                  <div class="step-detail-item">
                    <span class="sdi-label">步骤 ID</span>
                    <span class="sdi-value"><code>{{ step.task_log_id }}</code></span>
                  </div>
                  <div class="step-detail-item">
                    <span class="sdi-label">时间</span>
                    <span class="sdi-value">{{ formatDate(step.created_at) }}</span>
                  </div>
                  <div v-if="step.url_before" class="step-detail-item full-width">
                    <span class="sdi-label">URL 跳转前</span>
                    <span class="sdi-value url-text">{{ step.url_before }}</span>
                  </div>
                  <div v-if="step.url_after" class="step-detail-item full-width">
                    <span class="sdi-label">URL 跳转后</span>
                    <span class="sdi-value url-text">{{ step.url_after }}</span>
                  </div>
                  <div v-if="step.error" class="step-detail-item full-width">
                    <span class="sdi-label">错误</span>
                    <span class="sdi-value error-text">{{ step.error }}</span>
                  </div>
                  <div v-if="step.error_code" class="step-detail-item">
                    <span class="sdi-label">错误码</span>
                    <span class="sdi-value"><code>{{ step.error_code }}</code></span>
                  </div>
                </div>

                <div v-if="step.params && Object.keys(step.params).length" class="step-extras">
                  <button class="extras-toggle" @click="toggleExtra(step.task_log_id, 'params')">
                    <svg :class="['chevron', { open: extraOpen(step.task_log_id, 'params') }]" viewBox="0 0 16 16" fill="none" width="12" height="12"><path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
                    步骤参数
                  </button>
                  <div v-if="extraOpen(step.task_log_id, 'params')" class="extras-content">
                    <pre class="code-block">{{ prettyJson(step.params) }}</pre>
                  </div>
                </div>

                <div v-if="step.screenshot_path" class="step-extras">
                  <button class="extras-toggle" @click="toggleExtra(step.task_log_id, 'screenshot')">
                    <svg :class="['chevron', { open: extraOpen(step.task_log_id, 'screenshot') }]" viewBox="0 0 16 16" fill="none" width="12" height="12"><path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
                    步骤截图
                  </button>
                  <div v-if="extraOpen(step.task_log_id, 'screenshot')" class="extras-content">
                    <p class="screenshot-path">截图：<code>{{ step.screenshot_path }}</code></p>
                    <img
                      class="screenshot"
                      :src="screenshotSrc(step.screenshot_path)"
                      :alt="'步骤 ' + step.step_number + ' 截图'"
                      loading="lazy"
                      @click="openLightbox(step.screenshot_path, step.step_number)"
                    />
                  </div>
                </div>
              </div>
            </article>
          </div>
          <el-empty v-else description="暂无执行步骤"/>
        </section>

        <!-- Findings -->
        <section class="section section-card" id="findings" data-section>
          <div class="section-head">
            <div class="section-title-group">
              <div class="section-icon">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M10 2l3 6 6 .5-4.5 4.5L16 19l-6-3-6 3 1.5-6L1 8.5 7 8l3-6z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
              </div>
              <div>
                <h2>问题清单</h2>
                <p class="section-subtitle">展示测试过程中识别到的缺陷、异常、风险或未完成目标。</p>
              </div>
            </div>
            <span :class="['status-badge', findingCount === 0 ? 'badge-success' : 'badge-danger']">
              {{ findingCount }} 个问题
            </span>
          </div>

          <div v-if="report.findings.length" class="findings-list">
            <article
              v-for="(finding, index) in report.findings"
              :key="finding.finding_id"
              :id="'finding-' + index"
              :class="['finding-card', 'sev-' + finding.severity]"
            >
              <div class="finding-indicator" :class="'sev-bar-' + finding.severity"/>
              <div class="finding-body">
                <div class="finding-header">
                  <div class="finding-title-row">
                    <h3 class="finding-title">{{ finding.title }}</h3>
                    <span :class="['severity-tag', 'sev-tag-' + finding.severity]">{{ finding.severity }}</span>
                  </div>
                  <p class="finding-desc">{{ finding.description }}</p>
                </div>
                <div class="finding-meta-grid">
                  <div class="fm-item">
                    <span class="fm-label">问题 ID</span>
                    <span class="fm-value"><code>{{ finding.finding_id }}</code></span>
                  </div>
                  <div class="fm-item">
                    <span class="fm-label">类型</span>
                    <span class="fm-value">{{ finding.finding_type }}</span>
                  </div>
                  <div v-if="finding.url" class="fm-item full-width">
                    <span class="fm-label">URL</span>
                    <span class="fm-value url-text">{{ finding.url }}</span>
                  </div>
                  <div v-if="finding.location" class="fm-item full-width">
                    <span class="fm-label">位置</span>
                    <span class="fm-value">{{ finding.location }}</span>
                  </div>
                  <div class="fm-item">
                    <span class="fm-label">时间</span>
                    <span class="fm-value">{{ formatDate(finding.created_at) }}</span>
                  </div>
                </div>
                <div v-if="finding.screenshot_path" class="finding-extras">
                  <button class="extras-toggle" @click="toggleExtra(finding.finding_id, 'screenshot')">
                    <svg :class="['chevron', { open: extraOpen(finding.finding_id, 'screenshot') }]" viewBox="0 0 16 16" fill="none" width="12" height="12"><path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
                    问题截图
                  </button>
                  <div v-if="extraOpen(finding.finding_id, 'screenshot')" class="extras-content">
                    <p class="screenshot-path">截图：<code>{{ finding.screenshot_path }}</code></p>
                    <img
                      class="screenshot"
                      :src="screenshotSrc(finding.screenshot_path)"
                      :alt="finding.title + ' 截图'"
                      loading="lazy"
                      @click="openLightbox(finding.screenshot_path, null)"
                    />
                  </div>
                </div>
              </div>
            </article>
          </div>
          <el-empty v-else description="未记录问题"/>
        </section>

        <!-- Raw JSON -->
        <section class="section section-card" id="raw-json" data-section>
          <div class="section-head">
            <div class="section-title-group">
              <div class="section-icon">
                <svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M5 7l-3 3 3 3M15 7l3 3-3 3M12 4l-4 12" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
              </div>
              <div>
                <h2>原始 JSON</h2>
                <p class="section-subtitle">完整结构化报告内容，可用于排查、归档或二次处理。</p>
              </div>
            </div>
          </div>
          <button class="extras-toggle" @click="rawJsonOpen = !rawJsonOpen">
            <svg :class="['chevron', { open: rawJsonOpen }]" viewBox="0 0 16 16" fill="none" width="12" height="12"><path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
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
          <svg viewBox="0 0 20 20" fill="none" width="20" height="20"><path d="M5 5l10 10M15 5l-10 10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
        </button>
        <img class="lightbox-img" :src="screenshotSrc(lightboxSrc)" alt="截图全屏预览"/>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import {computed, ref, onMounted, onUnmounted} from "vue";
import type {FindingSeverity, ReportData} from "../types";
import {screenshotUrl} from "../api";

const props = defineProps<{
  report: ReportData | null;
  loading: boolean;
  taskId: string;
}>();

// --- reactive state ---
const activeSection = ref("");
const rawJsonOpen = ref(false);
const extrasOpen = ref<Record<string, boolean>>({});
const lightboxSrc = ref<string | null>(null);
const observer = ref<IntersectionObserver | null>(null);

// --- nav items ---
const navItems = [
  { id: "overview", label: "概览", index: "01" },
  { id: "task", label: "任务信息", index: "02" },
  { id: "steps", label: "执行步骤", index: "03" },
  { id: "findings", label: "问题清单", index: "04" },
  { id: "raw-json", label: "原始 JSON", index: "05" },
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
function formatDate(value: string | null): string {
  if (!value) return "-";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function screenshotSrc(path: string): string {
  return screenshotUrl(props.taskId, path);
}

function toggleExtra(id: string, type: string): void {
  const key = `${id}:${type}`;
  extrasOpen.value[key] = !extrasOpen.value[key];
}

function extraOpen(id: string, type: string): boolean {
  return !!extrasOpen.value[`${id}:${type}`];
}

function scrollTo(id: string): void {
  const el = document.getElementById(id);
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function openLightbox(path: string, _step: number | null): void {
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
    { rootMargin: "-80px 0px -60% 0px" }
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
  --rp-bg: #f4f6f9;
  --rp-surface: #ffffff;
  --rp-line: #e6edf0;
  --rp-line-light: #f0f4f7;
  --rp-text: #1a2a32;
  --rp-muted: #687a85;
  --rp-muted-light: #94a6b0;
  --radius: 10px;
  --radius-sm: 6px;
  --shadow-sm: 0 1px 3px rgba(24, 40, 50, 0.06);
  --shadow-md: 0 4px 12px rgba(24, 40, 50, 0.07);
  --shadow-lg: 0 8px 30px rgba(24, 40, 50, 0.10);
  --transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  --accent: #3b82f6;
  --success: #10b981;
  --danger: #ef4444;
  --warning: #f59e0b;
  --info: #6b8a9e;
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--rp-bg);
  scroll-behavior: smooth;
}

/* ===== Hero ===== */
.report-hero {
  position: relative;
  background: linear-gradient(135deg, #0a1e24 0%, #0f2a32 40%, #122f38 100%);
  color: #dce8eb;
  padding: 44px 40px 40px;
  overflow: hidden;
}
.hero-bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: radial-gradient(ellipse 80% 60% at 50% 0%, black, transparent 80%);
  -webkit-mask-image: radial-gradient(ellipse 80% 60% at 50% 0%, black, transparent 80%);
}
.hero-inner {
  position: relative;
  max-width: 1100px;
  display: flex;
  justify-content: space-between;
  gap: 32px;
  flex-wrap: wrap;
}
.hero-main {
  flex: 1;
  min-width: 280px;
}
.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: #7ab0b8;
  margin-bottom: 12px;
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.08);
  padding: 3px 12px 3px 10px;
  border-radius: 999px;
}
.report-hero h1 {
  margin: 0 0 10px;
  color: #ffffff;
  font-size: 28px;
  font-weight: 740;
  letter-spacing: -0.4px;
  line-height: 1.25;
}
.hero-desc {
  margin: 0 0 20px;
  color: #bcd8de;
  font-size: 14px;
  line-height: 1.65;
  max-width: 640px;
}
.hero-status {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* Status Badges */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 12px 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 580;
  letter-spacing: 0.2px;
  background: rgba(255,255,255,0.1);
  color: #dce8eb;
  border: 1px solid rgba(255,255,255,0.1);
}
.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.badge-completed .badge-dot { background: var(--success); }
.badge-failed .badge-dot,
.badge-timeout .badge-dot,
.badge-cancelled .badge-dot { background: var(--danger); }
.badge-running .badge-dot { background: var(--warning); animation: pulse-dot 1.5s ease infinite; }
.badge-pending .badge-dot { background: var(--info); }
.badge-success { background: rgba(16,185,129,0.15); color: #34d399; border-color: rgba(16,185,129,0.2); }
.badge-danger { background: rgba(239,68,68,0.15); color: #f87171; border-color: rgba(239,68,68,0.2); }
.badge-info { background: rgba(255,255,255,0.08); color: #bcd8de; border-color: rgba(255,255,255,0.08); }
@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.hero-meta {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius);
  padding: 16px 20px;
  display: grid;
  gap: 10px;
  min-width: 240px;
  align-content: start;
  backdrop-filter: blur(8px);
}
.meta-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.meta-label {
  color: #7ab0b8;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  white-space: nowrap;
}
.meta-value {
  color: #e4ebee;
  font-size: 12px;
  text-align: right;
  word-break: break-all;
}

/* ===== Layout ===== */
.report-layout {
  max-width: 1100px;
  margin: 0 auto;
  padding: 32px 40px 80px;
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 28px;
  align-items: start;
}
.report-sidebar {
  position: sticky;
  top: 24px;
}

/* Nav */
.nav-card {
  border: 1px solid var(--rp-line);
  border-radius: var(--radius);
  background: var(--rp-surface);
  box-shadow: var(--shadow-sm);
  padding: 12px;
  display: grid;
  gap: 2px;
}
.nav-title {
  margin: 0 0 4px 8px;
  color: var(--rp-muted);
  font-size: 10px;
  font-weight: 680;
  letter-spacing: 0.8px;
  text-transform: uppercase;
}
.nav-link {
  display: flex;
  align-items: center;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  color: var(--rp-muted-light);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  transition: all var(--transition);
}
.nav-link:hover {
  background: #f0f5f8;
  color: var(--rp-text);
}
.nav-link.active {
  background: #eef4ff;
  color: var(--accent);
  font-weight: 600;
}
.nav-link-text {
  display: flex;
  align-items: center;
  gap: 8px;
}
.nav-index {
  font-size: 10px;
  font-weight: 600;
  color: inherit;
  opacity: 0.5;
  min-width: 16px;
}
.nav-link.active .nav-index {
  opacity: 0.8;
}

/* ===== Main ===== */
.report-main {
  min-width: 0;
  display: grid;
  gap: 24px;
}
.section {
  display: grid;
  gap: 16px;
}
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
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
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: #eef4ff;
  color: var(--accent);
  flex-shrink: 0;
  margin-top: 1px;
}
.section-head h2 {
  margin: 0;
  color: var(--rp-text);
  font-size: 17px;
  font-weight: 680;
  line-height: 1.3;
}
.section-subtitle {
  margin: 2px 0 0;
  color: var(--rp-muted);
  font-size: 13px;
  line-height: 1.5;
}

/* ===== Section Card ===== */
.section-card {
  border: 1px solid var(--rp-line);
  border-radius: var(--radius);
  background: var(--rp-surface);
  box-shadow: var(--shadow-sm);
  padding: 24px;
  transition: box-shadow var(--transition);
}
.section-card:hover {
  box-shadow: var(--shadow-md);
}

/* ===== Metrics ===== */
.metrics {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}
.r-metric {
  display: flex;
  align-items: center;
  gap: 14px;
  border: 1px solid var(--rp-line);
  border-radius: var(--radius);
  background: var(--rp-surface);
  padding: 16px;
  box-shadow: var(--shadow-sm);
  transition: all var(--transition);
  border-left: 3px solid transparent;
}
.r-metric:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}
.metric-accent-primary { border-left-color: var(--accent); }
.metric-accent-success { border-left-color: var(--success); }
.metric-accent-danger { border-left-color: var(--danger); }
.metric-accent-warning { border-left-color: var(--warning); }
.metric-accent-info { border-left-color: var(--info); }

.metric-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  flex-shrink: 0;
}
.mi-primary { background: #eef4ff; color: var(--accent); }
.mi-success { background: #ecfdf5; color: var(--success); }
.mi-danger { background: #fef2f2; color: var(--danger); }
.mi-warning { background: #fffbeb; color: var(--warning); }
.mi-info { background: #f0f4f7; color: var(--info); }

.metric-body {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.metric-label {
  font-size: 11px;
  color: var(--rp-muted);
  font-weight: 500;
  white-space: nowrap;
}
.metric-value {
  font-size: 22px;
  font-weight: 720;
  color: var(--rp-text);
  letter-spacing: -0.4px;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ===== Info Table ===== */
.info-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 4px;
}
.info-table th, .info-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--rp-line-light);
  text-align: left;
  vertical-align: top;
  font-size: 13px;
}
.info-table th {
  width: 100px;
  color: var(--rp-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  white-space: nowrap;
}
.info-table td {
  color: var(--rp-text);
  word-break: break-word;
}
.info-table tr:last-child th,
.info-table tr:last-child td {
  border-bottom: 0;
}
.info-table code, code {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  background: #f0f4f7;
  padding: 1px 6px;
  border-radius: 4px;
  color: #2d4756;
}

/* ===== Timeline ===== */
.timeline {
  position: relative;
  display: grid;
  gap: 16px;
  padding-left: 28px;
}
.timeline-line {
  position: absolute;
  left: 10px;
  top: 8px;
  bottom: 8px;
  width: 2px;
  background: #dfe7ec;
  border-radius: 1px;
}

.step-card {
  position: relative;
  border: 1px solid var(--rp-line);
  border-radius: var(--radius);
  background: var(--rp-surface);
  box-shadow: var(--shadow-sm);
  transition: all var(--transition);
}
.step-card:hover {
  box-shadow: var(--shadow-md);
}

.step-node {
  position: absolute;
  left: -28px;
  top: 16px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  font-weight: 700;
  z-index: 1;
  box-shadow: 0 0 0 3px var(--rp-bg);
}
.node-success { background: var(--success); color: #fff; }
.node-failed { background: var(--danger); color: #fff; }
.node-skipped { background: #d1d9df; color: var(--rp-muted); }

.step-card-body {
  padding: 16px 18px;
  display: grid;
  gap: 12px;
}

.step-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}
.step-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.step-title {
  margin: 0;
  font-size: 14px;
  font-weight: 620;
  color: var(--rp-text);
}
.step-pill {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  background: #e8f0f4;
  color: #4b6572;
  letter-spacing: 0.2px;
  white-space: nowrap;
}

.step-result-tag {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}
.tag-success { background: #ecfdf5; color: #059669; }
.tag-failed { background: #fef2f2; color: #dc2626; }
.tag-skipped { background: #f3f6f8; color: var(--rp-muted); }

.step-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px 16px;
}
.step-detail-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.step-detail-item.full-width {
  grid-column: 1 / -1;
}
.sdi-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--rp-muted);
  letter-spacing: 0.3px;
  text-transform: uppercase;
}
.sdi-value {
  font-size: 12px;
  color: var(--rp-text);
  word-break: break-word;
}

/* ===== Extras / Toggles ===== */
.step-extras {
  margin-top: 2px;
}
.extras-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid var(--rp-line);
  border-radius: var(--radius-sm);
  background: #fafcfd;
  color: var(--rp-muted);
  font-size: 12px;
  font-weight: 550;
  cursor: pointer;
  transition: all var(--transition);
  font-family: inherit;
}
.extras-toggle:hover {
  background: #f0f5f8;
  color: var(--rp-text);
  border-color: #d0dbdf;
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
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

.code-block {
  margin: 0;
  padding: 14px;
  border-radius: var(--radius-sm);
  background: #1a2a32;
  color: #dce8eb;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  line-height: 1.65;
  overflow-x: auto;
  white-space: pre;
}
.json-block {
  max-height: 520px;
  overflow: auto;
}

/* ===== Screenshots ===== */
.screenshot-path {
  margin: 0 0 8px;
  color: var(--rp-muted);
  font-size: 11px;
}
.screenshot {
  max-width: 100%;
  border-radius: var(--radius-sm);
  border: 1px solid var(--rp-line);
  box-shadow: var(--shadow-sm);
  cursor: zoom-in;
  transition: box-shadow var(--transition);
}
.screenshot:hover {
  box-shadow: var(--shadow-md);
}

/* ===== Failure Summary ===== */
.failure-summary {
  border: 1px solid #fee2e2;
  border-radius: var(--radius);
  background: #fefaf9;
  padding: 16px 18px;
}
.failure-summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--danger);
  font-size: 13px;
  font-weight: 550;
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
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: #ffffff;
  border: 1px solid #fee2e2;
  text-decoration: none;
  color: var(--rp-text);
  font-size: 12px;
  transition: all var(--transition);
}
.failure-chip:hover {
  background: #fef2f2;
  border-color: #fecaca;
  box-shadow: var(--shadow-sm);
}
.failure-step-num {
  font-weight: 650;
  color: var(--danger);
  flex-shrink: 0;
  font-size: 12px;
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
  display: grid;
  gap: 12px;
}
.finding-card {
  display: flex;
  border: 1px solid var(--rp-line);
  border-radius: var(--radius);
  background: var(--rp-surface);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: all var(--transition);
}
.finding-card:hover {
  box-shadow: var(--shadow-md);
}
.finding-indicator {
  width: 4px;
  flex-shrink: 0;
}
.sev-bar-critical { background: #7f1d1d; }
.sev-bar-high { background: var(--danger); }
.sev-bar-medium { background: var(--warning); }
.sev-bar-low { background: #3b82f6; }
.sev-bar-info { background: var(--info); }

.finding-body {
  flex: 1;
  padding: 16px 18px;
  display: grid;
  gap: 12px;
}
.finding-header {
  display: grid;
  gap: 4px;
}
.finding-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.finding-title {
  margin: 0;
  font-size: 14px;
  font-weight: 620;
  color: var(--rp-text);
}
.finding-desc {
  margin: 0;
  font-size: 13px;
  color: var(--rp-muted);
  line-height: 1.5;
}
.severity-tag {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.3px;
  text-transform: uppercase;
}
.sev-tag-critical { background: #fef2f2; color: #991b1b; }
.sev-tag-high { background: #fef2f2; color: #dc2626; }
.sev-tag-medium { background: #fffbeb; color: #d97706; }
.sev-tag-low { background: #eef4ff; color: #2563eb; }
.sev-tag-info { background: #f0f4f7; color: var(--info); }

.finding-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 4px 16px;
}
.fm-item {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.fm-item.full-width { grid-column: 1 / -1; }
.fm-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--rp-muted);
  letter-spacing: 0.3px;
  text-transform: uppercase;
}
.fm-value {
  font-size: 12px;
  color: var(--rp-text);
  word-break: break-word;
}

.finding-extras {
  margin-top: 2px;
}

/* ===== Lightbox ===== */
.lightbox-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0,0,0,0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  cursor: zoom-out;
  animation: fadeIn 0.2s ease;
}
.lightbox-close {
  position: absolute;
  top: 16px;
  right: 16px;
  background: rgba(255,255,255,0.1);
  border: none;
  color: #fff;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background var(--transition);
}
.lightbox-close:hover {
  background: rgba(255,255,255,0.2);
}
.lightbox-img {
  max-width: 100%;
  max-height: 100%;
  border-radius: 8px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  object-fit: contain;
}

/* ===== Utility ===== */
.muted {
  color: var(--rp-muted);
}
.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
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
@media (max-width: 1000px) {
  .metrics {
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  }
}
@media (max-width: 900px) {
  .report-layout {
    grid-template-columns: 1fr;
    padding: 20px 16px 40px;
  }
  .report-sidebar {
    position: static;
  }
  .nav-card {
    display: flex;
    gap: 4px;
    overflow-x: auto;
    padding: 8px;
  }
  .nav-title { display: none; }
  .nav-link {
    white-space: nowrap;
    font-size: 12px;
    padding: 6px 12px;
  }
  .nav-index { display: none; }
  .report-hero {
    padding: 28px 20px 24px;
  }
  .hero-inner {
    flex-direction: column;
  }
  .hero-meta {
    min-width: 0;
  }
  .step-detail-grid {
    grid-template-columns: 1fr;
  }
  .finding-meta-grid {
    grid-template-columns: 1fr;
  }
  .section-card {
    padding: 16px;
  }
}
</style>
