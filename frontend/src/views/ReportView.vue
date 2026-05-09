<template>
  <div v-if="loading" class="empty-state">
    <el-empty description="正在加载报告"/>
  </div>
  <div v-else-if="!report" class="empty-state">
    <el-empty description="该任务尚未生成报告，请先执行任务。"/>
  </div>
  <div v-else class="report-container">
    <header class="report-hero">
      <div class="hero-inner">
        <div>
          <div class="eyebrow">Argus Blackbox Testing</div>
          <h1>{{ report.title }}</h1>
          <p class="hero-desc">{{ summary }}</p>
          <div class="hero-status">
            <el-tag :type="statusTagType" size="small">{{ status }}</el-tag>
            <el-tag :type="findingCount === 0 ? 'success' : 'danger'" size="small">问题 {{ findingCount }}</el-tag>
            <el-tag type="info" size="small">步骤 {{ stepCount }} / {{ report.task.max_steps }}</el-tag>
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

    <div class="report-layout">
      <aside class="report-sidebar">
        <nav class="nav-card">
          <p class="nav-title">Report Sections</p>
          <a class="nav-link" href="#overview"><span>概览</span><span>01</span></a>
          <a class="nav-link" href="#task"><span>任务信息</span><span>02</span></a>
          <a class="nav-link" href="#steps"><span>执行步骤</span><span>03</span></a>
          <a class="nav-link" href="#findings"><span>问题清单</span><span>04</span></a>
          <a class="nav-link" href="#raw-json"><span>原始 JSON</span><span>05</span></a>
        </nav>
      </aside>

      <main class="report-main">
        <section class="section" id="overview">
          <div class="metrics">
            <div class="r-metric">
              <span>任务状态</span>
              <strong>
                <el-tag :type="statusTagType" size="small">{{ status }}</el-tag>
              </strong>
            </div>
            <div class="r-metric"><span>展示步骤</span><strong>{{ stepCount }}</strong></div>
            <div class="r-metric"><span>问题数量</span><strong>{{ findingCount }}</strong></div>
            <div class="r-metric"><span>失败步骤</span><strong>{{ failedCount }}</strong></div>
            <div class="r-metric"><span>最大步数</span><strong>{{ report.task.max_steps }}</strong></div>
          </div>
        </section>

        <section class="section r-card" id="task">
          <div class="section-head">
            <div>
              <h2>任务信息</h2>
              <p class="section-subtitle">记录测试目标、入口地址、执行结果与时间线。</p>
            </div>
            <el-tag :type="statusTagType" size="small">{{ status }}</el-tag>
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
              <td>{{ report.task.start_url || '' }}</td>
            </tr>
            <tr>
              <th>结果摘要</th>
              <td>{{ summary }}</td>
            </tr>
            <tr>
              <th>报告路径</th>
              <td><code>{{ report.task.report_path || '' }}</code></td>
            </tr>
            <tr>
              <th>错误信息</th>
              <td>
                <span v-if="report.task.error_message">{{ report.task.error_message }}</span>
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

        <section class="section" id="steps">
          <div class="section-head">
            <div>
              <h2>执行步骤</h2>
              <p class="section-subtitle">
                按照 Agent 实际操作顺序展示关键动作。
                <template v-if="report.hidden_steps_count > 0">
                  已隐藏 {{ report.hidden_steps_count }} 个内部等待或纯截图步骤。
                </template>
              </p>
            </div>
            <el-tag :type="failedCount === 0 ? 'success' : 'danger'" size="small">
              失败 {{ failedCount }}
            </el-tag>
          </div>

          <div v-if="failedSteps.length" class="r-card failure-summary">
            <h3>失败步骤聚合</h3>
            <p class="section-subtitle">以下步骤执行失败，可直接跳转到对应步骤查看参数、URL 和截图证据。</p>
            <table class="info-table">
              <tbody>
              <tr v-for="step in failedSteps" :key="step.step_number">
                <th>#{{ step.step_number }} {{ step.action }}</th>
                <td>
                  <a :href="'#step-' + step.step_number">
                    {{ step.error || step.message || '未记录错误详情' }}
                  </a>
                </td>
              </tr>
              </tbody>
            </table>
          </div>

          <div v-if="displaySteps.length" class="timeline">
            <article
                v-for="step in displaySteps"
                :key="step.task_log_id"
                :id="'step-' + step.step_number"
                :class="['step', 'result-' + step.result]"
            >
              <div class="step-head">
                <div>
                  <div class="step-title">
                    <h3>{{ step.message || step.action }}</h3>
                    <span class="action-pill">{{ step.action }}</span>
                  </div>
                  <p class="muted">{{ step.message || '未记录步骤说明。' }}</p>
                </div>
                <el-tag :type="step.result === 'success' ? 'success' : 'danger'" size="small">{{ step.result }}</el-tag>
              </div>
              <div class="step-body">
                <table class="info-table">
                  <tbody>
                  <tr>
                    <th>步骤 ID</th>
                    <td><code>{{ step.task_log_id }}</code></td>
                  </tr>
                  <tr>
                    <th>URL Before</th>
                    <td>
                      <template v-if="step.url_before">{{ step.url_before }}</template>
                      <span v-else class="muted">未记录</span>
                    </td>
                  </tr>
                  <tr>
                    <th>URL After</th>
                    <td>
                      <template v-if="step.url_after">{{ step.url_after }}</template>
                      <span v-else class="muted">未记录</span>
                    </td>
                  </tr>
                  <tr>
                    <th>错误</th>
                    <td>
                      <template v-if="step.error">{{ step.error }}</template>
                      <span v-else class="muted">无</span>
                    </td>
                  </tr>
                  <tr v-if="step.error_code">
                    <th>错误码</th>
                    <td><code>{{ step.error_code }}</code></td>
                  </tr>
                  <tr>
                    <th>时间</th>
                    <td>{{ formatDate(step.created_at) }}</td>
                  </tr>
                  </tbody>
                </table>

                <details v-if="step.params && Object.keys(step.params).length">
                  <summary>步骤参数</summary>
                  <pre class="params">{{ prettyJson(step.params) }}</pre>
                </details>

                <details v-if="step.screenshot_path">
                  <summary>步骤截图</summary>
                  <div class="screenshot-wrap">
                    <p class="screenshot-path">截图：<code>{{ step.screenshot_path }}</code></p>
                    <img class="screenshot" :src="screenshotSrc(step.screenshot_path)"
                         :alt="'步骤 ' + step.step_number + ' 截图'" loading="lazy"/>
                  </div>
                </details>
              </div>
            </article>
          </div>
          <el-empty v-else description="暂无执行步骤"/>
        </section>

        <section class="section r-card" id="findings">
          <div class="section-head">
            <div>
              <h2>问题清单</h2>
              <p class="section-subtitle">展示测试过程中识别到的缺陷、异常、风险或未完成目标。</p>
            </div>
            <el-tag :type="findingCount === 0 ? 'success' : 'danger'" size="small">{{ findingCount }} findings</el-tag>
          </div>

          <div v-if="report.findings.length" class="timeline">
            <article
                v-for="(finding, index) in report.findings"
                :key="finding.finding_id"
                :id="'finding-' + index"
                :class="['step', 'result-' + finding.severity]"
            >
              <div class="finding-head">
                <div>
                  <div class="step-title">
                    <h3>{{ finding.title }}</h3>
                    <span class="action-pill">{{ finding.finding_type }}</span>
                  </div>
                  <p class="muted">{{ finding.description }}</p>
                </div>
                <el-tag :type="severityTagType(finding.severity)" size="small">{{ finding.severity }}</el-tag>
              </div>
              <div class="step-body">
                <table class="info-table">
                  <tbody>
                  <tr>
                    <th>问题 ID</th>
                    <td><code>{{ finding.finding_id }}</code></td>
                  </tr>
                  <tr>
                    <th>类型</th>
                    <td>{{ finding.finding_type }}</td>
                  </tr>
                  <tr>
                    <th>URL</th>
                    <td>{{ finding.url || '' }}</td>
                  </tr>
                  <tr>
                    <th>位置</th>
                    <td>{{ finding.location || '' }}</td>
                  </tr>
                  <tr>
                    <th>时间</th>
                    <td>{{ formatDate(finding.created_at) }}</td>
                  </tr>
                  </tbody>
                </table>
                <details v-if="finding.screenshot_path">
                  <summary>问题截图</summary>
                  <div class="screenshot-wrap">
                    <p class="screenshot-path">截图：<code>{{ finding.screenshot_path }}</code></p>
                    <img class="screenshot" :src="screenshotSrc(finding.screenshot_path)" :alt="finding.title + ' 截图'"
                         loading="lazy"/>
                  </div>
                </details>
              </div>
            </article>
          </div>
          <el-empty v-else description="未记录问题"/>
        </section>

        <section class="section r-card" id="raw-json">
          <div class="section-head">
            <div>
              <h2>原始 JSON</h2>
              <p class="section-subtitle">完整结构化报告内容，可用于排查、归档或二次处理。</p>
            </div>
          </div>
          <details>
            <summary>查看原始 JSON</summary>
            <pre class="raw-json">{{ reportJson }}</pre>
          </details>
        </section>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import {computed} from "vue";
import type {FindingSeverity, ReportData} from "../types";
import {screenshotUrl} from "../api";

const props = defineProps<{
  report: ReportData | null;
  loading: boolean;
  taskId: string;
}>();

const status = computed(() => props.report?.task?.status ?? "");
const summary = computed(() => props.report?.summary || props.report?.task?.result_summary || "未记录结果摘要。");
const displaySteps = computed(() => props.report?.display_steps ?? []);
const failedSteps = computed(() => displaySteps.value.filter((s) => s.result === "failed"));
const failedCount = computed(() => failedSteps.value.length);
const findingCount = computed(() => props.report?.findings?.length ?? 0);
const stepCount = computed(() => displaySteps.value.length);
const reportJson = computed(() => prettyJson(props.report));

const statusTagType = computed(() => {
  const s = status.value;
  if (s === "completed") return "success";
  if (s === "failed" || s === "timeout" || s === "cancelled") return "danger";
  if (s === "running") return "warning";
  return "info";
});

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

function severityTagType(severity: FindingSeverity): string {
  if (severity === "high" || severity === "critical") return "danger";
  if (severity === "medium") return "warning";
  return "info";
}
</script>

<style scoped>
/* ===== Report Container ===== */
.report-container {
  --report-bg: #f8fafb;
  --report-line: #e4ebee;
  --report-text: #273237;
  --report-muted: #6a7a83;
  --radius-sm: 6px;
  --radius: 8px;
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--report-bg);
}

/* ===== Hero Header ===== */
.report-hero {
  background: linear-gradient(135deg, #0d2328 0%, #173438 100%);
  color: #dce8eb;
  padding: 36px 40px;
}

.hero-inner {
  max-width: 1100px;
  display: flex;
  justify-content: space-between;
  gap: 32px;
  flex-wrap: wrap;
}

.eyebrow {
  font-size: 11px;
  font-weight: 640;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: #82b3b8;
  margin-bottom: 8px;
}

.report-hero h1 {
  margin: 0 0 10px;
  color: #ffffff;
  font-size: 26px;
  font-weight: 720;
  letter-spacing: -0.3px;
}

.hero-desc {
  margin: 0 0 16px;
  color: #b4cfd4;
  font-size: 14px;
  line-height: 1.6;
}

.hero-status {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.hero-meta {
  background: rgb(255 255 255 / 8%);
  border: 1px solid rgb(255 255 255 / 10%);
  border-radius: var(--radius);
  padding: 16px 20px;
  display: grid;
  gap: 10px;
  min-width: 260px;
  align-content: start;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.meta-label {
  color: #82b3b8;
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
  padding: 28px 40px 60px;
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  gap: 32px;
  align-items: start;
}

.report-sidebar {
  position: sticky;
  top: 24px;
}

.nav-card {
  border: 1px solid var(--report-line);
  border-radius: var(--radius);
  background: #ffffff;
  box-shadow: 0 1px 3px rgb(24 33 37 / 5%);
  padding: 16px;
  display: grid;
  gap: 6px;
}

.nav-title {
  margin: 0 0 6px;
  color: var(--report-muted);
  font-size: 10px;
  font-weight: 680;
  letter-spacing: 0.6px;
  text-transform: uppercase;
}

.nav-link {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  color: var(--report-text);
  font-size: 13px;
  font-weight: 520;
  text-decoration: none;
  transition: background 0.12s ease;
}

.nav-link:hover {
  background: #eef3f5;
}

.nav-link span:last-child {
  color: var(--report-muted);
  font-size: 11px;
}

/* ===== Sections ===== */
.report-main {
  min-width: 0;
  display: grid;
  gap: 28px;
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

.section-head h2 {
  margin: 0;
  color: var(--report-text);
  font-size: 18px;
  font-weight: 680;
}

.section-subtitle {
  margin: 3px 0 0;
  color: var(--report-muted);
  font-size: 13px;
}

/* ===== Cards ===== */
.r-card {
  border: 1px solid var(--report-line);
  border-radius: var(--radius);
  background: #ffffff;
  box-shadow: 0 1px 3px rgb(24 33 37 / 5%);
  padding: 24px;
}

/* ===== Metrics ===== */
.metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(130px, 1fr));
  gap: 12px;
}

.r-metric {
  border: 1px solid var(--report-line);
  border-radius: var(--radius);
  background: #ffffff;
  padding: 18px 16px;
  box-shadow: 0 1px 3px rgb(24 33 37 / 5%);
}

.r-metric span {
  display: block;
  margin-bottom: 6px;
  color: var(--report-muted);
  font-size: 12px;
}

.r-metric strong {
  color: #11181c;
  font-size: 26px;
  font-weight: 740;
  letter-spacing: -0.5px;
}

/* ===== Tables ===== */
.info-table {
  width: 100%;
  border-collapse: collapse;
}

.info-table th, .info-table td {
  padding: 9px 12px;
  border-bottom: 1px solid #f2f6f8;
  text-align: left;
  vertical-align: top;
  font-size: 13px;
}

.info-table th {
  width: 110px;
  color: var(--report-muted);
  font-size: 11px;
  font-weight: 640;
  letter-spacing: 0.2px;
  text-transform: uppercase;
  white-space: nowrap;
}

.info-table td {
  color: var(--report-text);
  word-break: break-word;
}

.info-table tr:last-child th,
.info-table tr:last-child td {
  border-bottom: 0;
}

.info-table code, code {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  background: #f4f7f8;
  padding: 1px 6px;
  border-radius: 3px;
  color: #374e57;
}

/* ===== Timeline / Steps ===== */
.timeline {
  display: grid;
  gap: 12px;
}

.step {
  border: 1px solid var(--report-line);
  border-radius: var(--radius);
  background: #ffffff;
  overflow: hidden;
}

.step.result-success {
  border-left: 3px solid #16a34a;
}

.step.result-failed {
  border-left: 3px solid #dc2626;
}

.step.result-info {
  border-left: 3px solid #7a8a9a;
}

.step.result-low {
  border-left: 3px solid #5b7aad;
}

.step.result-medium {
  border-left: 3px solid #d97706;
}

.step.result-high, .step.result-critical {
  border-left: 3px solid #dc2626;
}

.step-head, .finding-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  background: #fafcfc;
  border-bottom: 1px solid #f2f6f8;
}

.step-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.step-title h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 640;
  color: var(--report-text);
}

.action-pill {
  display: inline-flex;
  align-items: center;
  min-height: 18px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  background: #e8eef1;
  color: #4b616e;
  letter-spacing: 0.2px;
  white-space: nowrap;
}

.step-body {
  padding: 14px 16px;
  display: grid;
  gap: 12px;
}

/* ===== Details / Expandables ===== */
details {
  border: 1px solid #eef3f5;
  border-radius: var(--radius-sm);
  padding: 10px 14px;
}

details[open] {
  padding-bottom: 14px;
}

summary {
  cursor: pointer;
  color: #4b616e;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 0;
  user-select: none;
}

summary:hover {
  color: var(--report-text);
}

.params {
  margin: 10px 0 0;
  padding: 12px;
  border-radius: var(--radius-sm);
  background: #272d32;
  color: #dce8eb;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre;
}

.raw-json {
  margin: 10px 0 0;
  max-height: 520px;
  overflow: auto;
  padding: 12px;
  border-radius: var(--radius-sm);
  background: #272d32;
  color: #dce8eb;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
  white-space: pre;
}

/* ===== Screenshots ===== */
.screenshot-wrap {
  margin-top: 10px;
  display: grid;
  gap: 10px;
}

.screenshot-path {
  margin: 0;
  color: var(--report-muted);
  font-size: 11px;
}

.screenshot {
  max-width: 100%;
  border-radius: var(--radius-sm);
  border: 1px solid var(--report-line);
  box-shadow: 0 2px 8px rgb(24 33 37 / 8%);
}

/* ===== Failure Summary ===== */
.failure-summary {
  margin-bottom: 4px;
}

.failure-summary h3 {
  margin: 0 0 4px;
  color: #dc2626;
  font-size: 14px;
  font-weight: 650;
}

/* ===== Empty States ===== */
.empty-state {
  text-align: center;
  padding: 48px 24px;
}

/* ===== Utility ===== */
.muted {
  color: var(--report-muted);
}

.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
}

/* ===== Responsive ===== */
@media (max-width: 900px) {
  .report-layout {
    grid-template-columns: 1fr;
    padding: 20px 18px 40px;
  }

  .report-sidebar {
    position: static;
  }

  .nav-card {
    grid-template-columns: repeat(4, 1fr);
    gap: 4px;
  }

  .nav-title {
    display: none;
  }

  .nav-link {
    justify-content: center;
    font-size: 12px;
    padding: 6px;
  }

  .nav-link span:last-child {
    display: none;
  }

  .report-hero {
    padding: 24px 20px;
  }

  .hero-inner {
    flex-direction: column;
  }

  .metrics {
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  }
}
</style>
