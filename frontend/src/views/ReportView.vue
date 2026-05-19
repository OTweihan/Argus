<template>
  <div v-if="loading" class="empty-state">
    <el-empty description="正在加载报告" />
  </div>
  <div v-else-if="!report" class="empty-state">
    <el-empty description="该任务尚未生成报告，请先执行任务。" />
  </div>
  <div v-else class="report-container">
    <!-- Hero -->
    <ReportHero
      :report="report"
      :summary="summary"
      :status="status"
      :status-label="statusLabel"
      :finding-count="findingCount"
      :step-count="stepCount"
    />

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
          <ReportMetrics
            :status-label="statusLabel"
            :step-count="stepCount"
            :finding-count="findingCount"
            :failed-count="failedCount"
            :max-steps="report.task.maxSteps"
          />
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
                <td><code>{{ report.task.taskId }}</code></td>
              </tr>
              <tr>
                <th>目标</th>
                <td>{{ report.task.goal }}</td>
              </tr>
              <tr>
                <th>起始 URL</th>
                <td>{{ report.task.startUrl || '-' }}</td>
              </tr>
              <tr>
                <th>结果摘要</th>
                <td>{{ summary }}</td>
              </tr>
              <tr>
                <th>报告路径</th>
                <td><code>{{ report.task.reportPath || '-' }}</code></td>
              </tr>
              <tr>
                <th>错误信息</th>
                <td>
                  <span v-if="report.task.errorMessage" class="error-text">{{ report.task.errorMessage }}</span>
                  <span v-else class="muted">无</span>
                </td>
              </tr>
              <tr>
                <th>创建时间</th>
                <td>{{ formatDate(report.task.createdAt) }}</td>
              </tr>
              <tr>
                <th>开始时间</th>
                <td>{{ formatDate(report.task.startedAt) }}</td>
              </tr>
              <tr>
                <th>完成时间</th>
                <td>{{ formatDate(report.task.completedAt) }}</td>
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
                  <template v-if="report.hiddenStepsCount > 0">
                    已隐藏 {{ report.hiddenStepsCount }} 个内部等待或纯截图步骤。
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
                :key="step.stepNumber"
                :href="'#step-' + step.stepNumber"
                class="failure-chip"
                @click.prevent="scrollTo('step-' + step.stepNumber)"
              >
                <span class="failure-step-num">#{{ step.stepNumber }}</span>
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
              :key="step.taskLogId"
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
              :key="finding.findingId"
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
import {computed, ref} from "vue";
import type {ReportData} from "../types";
import {screenshotUrl} from "../api";
import {useScrollSpy} from "../composables/useScrollSpy";
import ReportHero from "../components/report/ReportHero.vue";
import ReportMetrics from "../components/report/ReportMetrics.vue";
import StepCard from "../components/task/report/StepCard.vue";
import FindingCard from "../components/task/report/FindingCard.vue";
import {
  REPORT_NAV_ITEMS,
  formatDate,
  getReportSummary,
  getStatusLabel,
  prettyJson,
} from "../components/task/report/reportUtils";

const props = defineProps<{
  report: ReportData | null;
  loading: boolean;
  taskId: string;
}>();

// --- reactive state ---
const { activeSection } = useScrollSpy();
const rawJsonOpen = ref(false);
const lightboxSrc = ref<string | null>(null);

// --- nav items ---
// 详见 reportUtils.ts，外部常量便于复用与单元测试。
const navItems = REPORT_NAV_ITEMS;

// --- computed ---
const status = computed(() => props.report?.task?.status ?? "");
const statusLabel = computed(() => getStatusLabel(status.value));
const summary = computed(() => getReportSummary(props.report));
const displaySteps = computed(() => props.report?.displaySteps ?? []);
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

</script>

<style scoped src="./report.css"></style>
<!-- P1-10：原 901 行 CSS 已抽到 ./report.css，保持 scoped 隔离不变。 -->
