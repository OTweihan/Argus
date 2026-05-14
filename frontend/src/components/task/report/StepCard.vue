<template>
  <article :id="'step-' + step.step_number" :class="['step-card', 'step-' + step.result]">
    <div class="step-node" :class="'node-' + step.result">
      <template v-if="step.result === 'success'">
        <svg viewBox="0 0 16 16" fill="none" width="10" height="10">
          <path d="M4 8l3 3 5-5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
        </svg>
      </template>
      <template v-else-if="step.result === 'failed'">
        <svg viewBox="0 0 16 16" fill="none" width="10" height="10">
          <path d="M5 5l6 6M11 5l-6 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
        </svg>
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
        <button class="extras-toggle" @click="paramsOpen = !paramsOpen">
          <svg :class="['chevron', { open: paramsOpen }]" viewBox="0 0 16 16" fill="none" width="12" height="12">
            <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
          </svg>
          步骤参数
        </button>
        <div v-if="paramsOpen" class="extras-content">
          <pre class="code-block">{{ prettyJson(step.params) }}</pre>
        </div>
      </div>

      <div v-if="step.screenshot_path" class="step-extras">
        <button class="extras-toggle" @click="screenshotOpen = !screenshotOpen">
          <svg :class="['chevron', { open: screenshotOpen }]" viewBox="0 0 16 16" fill="none" width="12" height="12">
            <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
          </svg>
          步骤截图
        </button>
        <div v-if="screenshotOpen" class="extras-content">
          <p class="screenshot-path">截图：<code>{{ step.screenshot_path }}</code></p>
          <img
              class="screenshot"
              :src="screenshotUrl(taskId, step.screenshot_path)"
              :alt="'步骤 ' + step.step_number + ' 截图'"
              loading="lazy"
              @click="$emit('open-lightbox', step.screenshot_path)"
          />
        </div>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { ref } from "vue";
import type { ReportTaskLog } from "../../../types";
import { screenshotUrl } from "../../../api";
import { formatDate, prettyJson } from "./reportUtils";

defineProps<{
  step: ReportTaskLog;
  taskId: string;
}>();

defineEmits<{
  (e: "open-lightbox", path: string): void;
}>();

const paramsOpen = ref(false);
const screenshotOpen = ref(false);
</script>

<style scoped>
/* 颜色 / 圆角 / 阴影变量由父级 .report-container 通过 CSS 继承提供。 */

.step-card {
  position: relative;
  border: 1px solid var(--rp-line);
  border-radius: var(--radius);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  transition: box-shadow var(--transition), transform var(--transition);
}

.step-failed {
  border-color: #fecdd3;
  background:
      linear-gradient(135deg, rgba(255, 241, 242, 0.85) 0%, rgba(255, 255, 255, 0.78) 55%);
  box-shadow: 0 8px 24px rgba(180, 35, 24, 0.08);
}

.step-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.step-node {
  position: absolute;
  left: -52px;
  top: 18px;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 800;
  z-index: 1;
  border: 3px solid #ffffff;
  box-shadow: 0 8px 20px rgba(79, 70, 229, 0.28);
}

.node-success {
  background-image: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: #fff;
}

.node-failed {
  background-image: linear-gradient(135deg, #b42318 0%, #dc2626 100%);
  color: #fff;
  box-shadow: 0 8px 20px rgba(180, 35, 24, 0.32);
}

.node-skipped {
  background: linear-gradient(135deg, #cbd5e1 0%, #94a3b8 100%);
  color: #ffffff;
}

.step-card-body {
  padding: 18px;
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
  font-size: 16px;
  font-weight: 700;
  color: var(--rp-text);
  line-height: 1.25;
}

.step-pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.step-result-tag {
  display: inline-flex;
  align-items: center;
  min-width: 76px;
  justify-content: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  flex-shrink: 0;
}

.tag-success {
  background: var(--success-soft);
  color: var(--success);
  border: 1px solid #bbf7d0;
}

.tag-failed {
  background: var(--danger-soft);
  color: var(--danger);
  border: 1px solid #fecdd3;
}

.tag-skipped {
  background: var(--info-soft);
  color: var(--info);
  border: 1px solid #b2ddff;
}

.step-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0;
  overflow: hidden;
  border: 1px solid var(--rp-line);
  border-radius: var(--radius-md);
  background: rgba(248, 250, 252, 0.55);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.step-detail-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--rp-line);
}

.step-detail-item.full-width {
  grid-column: 1 / -1;
}

.step-detail-item:nth-last-child(-n + 2):not(.full-width),
.step-detail-item:last-child {
  border-bottom: 0;
}

.sdi-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--rp-muted);
}

.sdi-value {
  font-size: 14px;
  color: var(--rp-text);
  overflow-wrap: anywhere;
}

.step-extras {
  margin-top: 2px;
  width: 100%;
}

.step-extras .extras-toggle,
.step-extras .extras-content {
  width: 100%;
}

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
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
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

.screenshot-path {
  margin: 12px 0;
  color: var(--rp-muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.screenshot {
  display: block;
  width: 100%;
  max-height: 520px;
  object-fit: contain;
  border-radius: var(--radius-md);
  border: 1px solid var(--rp-line);
  box-shadow: var(--shadow-sm);
  cursor: zoom-in;
  transition: box-shadow var(--transition);
}

.screenshot:hover {
  box-shadow: var(--shadow-md);
}

.error-text {
  color: var(--danger);
}

.url-text {
  color: var(--accent);
  word-break: break-all;
}

code {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
  background: #f2f4f7;
  padding: 2px 6px;
  border: 1px solid var(--rp-line);
  border-radius: 7px;
  color: #344054;
}

@media (max-width: 720px) {
  .step-detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
