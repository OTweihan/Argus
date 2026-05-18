<template>
  <article :id="'finding-' + index" :class="['finding-card', 'sev-' + finding.severity]">
    <div class="finding-indicator" :class="'sev-bar-' + finding.severity" />
    <div class="finding-body">
      <div class="finding-header">
        <div class="finding-title-row">
          <h3 class="finding-title">
            {{ finding.title }}
          </h3>
          <span :class="['severity-tag', 'sev-tag-' + finding.severity]">{{ finding.severity }}</span>
        </div>
        <p class="finding-desc">
          {{ finding.description }}
        </p>
      </div>
      <div class="finding-meta-grid">
        <div class="fm-item">
          <span class="fm-label">问题 ID</span>
          <span class="fm-value"><code>{{ finding.findingId }}</code></span>
        </div>
        <div class="fm-item">
          <span class="fm-label">类型</span>
          <span class="fm-value">{{ finding.findingType }}</span>
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
          <span class="fm-value">{{ formatDate(finding.createdAt) }}</span>
        </div>
      </div>
      <div v-if="finding.screenshotPath" class="finding-extras">
        <button class="extras-toggle" @click="screenshotOpen = !screenshotOpen">
          <svg :class="['chevron', { open: screenshotOpen }]" viewBox="0 0 16 16" fill="none" width="12" height="12">
            <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
          问题截图
        </button>
        <div v-if="screenshotOpen" class="extras-content">
          <p class="screenshot-path">
            截图：<code>{{ finding.screenshotPath }}</code>
          </p>
          <img
            class="screenshot"
            :src="screenshotUrl(taskId, finding.screenshotPath)"
            :alt="finding.title + ' 截图'"
            loading="lazy"
            @click="$emit('open-lightbox', finding.screenshotPath!)"
          >
        </div>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { ref } from "vue";
import type { ReportFinding } from "../../../types";
import { screenshotUrl } from "../../../api";
import { formatDate } from "./reportUtils";

defineProps<{
  finding: ReportFinding;
  index: number;
  taskId: string;
}>();

defineEmits<{
  (e: "open-lightbox", path: string): void;
}>();

const screenshotOpen = ref(false);
</script>

<style scoped>
.finding-card {
  display: flex;
  border: 1px solid var(--rp-line);
  border-radius: var(--radius);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  transition: box-shadow var(--transition), transform var(--transition);
}

.finding-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.sev-critical,
.sev-high {
  border-color: #fecdd3;
  background:
      linear-gradient(135deg, rgba(255, 241, 242, 0.85) 0%, rgba(255, 255, 255, 0.78) 55%);
  box-shadow: 0 8px 24px rgba(180, 35, 24, 0.08);
}

.finding-indicator {
  width: 5px;
  flex-shrink: 0;
}

.sev-bar-critical {
  background: linear-gradient(180deg, #7f1d1d 0%, #b42318 100%);
}

.sev-bar-high {
  background: linear-gradient(180deg, #b42318 0%, #dc2626 100%);
}

.sev-bar-medium {
  background: linear-gradient(180deg, #b54708 0%, #d97706 100%);
}

.sev-bar-low {
  background: linear-gradient(180deg, #6366f1 0%, #8b5cf6 100%);
}

.sev-bar-info {
  background: linear-gradient(180deg, #175cd3 0%, #2563eb 100%);
}

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
  font-size: 16px;
  font-weight: 700;
  color: var(--rp-text);
}

.finding-desc {
  margin: 0;
  font-size: 14px;
  color: var(--rp-muted);
  line-height: 1.5;
}

.severity-tag {
  display: inline-flex;
  align-items: center;
  min-width: 76px;
  justify-content: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

.sev-tag-critical {
  background: var(--danger-soft);
  color: #991b1b;
  border: 1px solid #fecdd3;
}

.sev-tag-high {
  background: var(--danger-soft);
  color: var(--danger);
  border: 1px solid #fecdd3;
}

.sev-tag-medium {
  background: var(--warning-soft);
  color: var(--warning);
  border: 1px solid #fedf89;
}

.sev-tag-low {
  background: var(--accent-soft);
  color: var(--accent);
  border: 1px solid #c7d2fe;
}

.sev-tag-info {
  background: var(--info-soft);
  color: var(--info);
  border: 1px solid #b2ddff;
}

.finding-meta-grid {
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

.fm-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--rp-line);
}

.fm-item.full-width {
  grid-column: 1 / -1;
}

.fm-item:nth-last-child(-n + 2):not(.full-width),
.fm-item:last-child {
  border-bottom: 0;
}

.fm-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--rp-muted);
}

.fm-value {
  font-size: 14px;
  color: var(--rp-text);
  overflow-wrap: anywhere;
}

.finding-extras {
  margin-top: 2px;
  width: 100%;
}

.finding-extras .extras-toggle,
.finding-extras .extras-content {
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
  .finding-meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
