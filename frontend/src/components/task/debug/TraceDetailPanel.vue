<template>
  <div class="dbg-detail">
    <div class="dbg-detail-header">
      <span class="dbg-detail-title">追踪详情</span>
      <div class="dbg-detail-actions">
        <button class="dbg-copy-btn" @click="copyPrompt">
          <svg viewBox="0 0 16 16" fill="none" width="13" height="13"><rect x="5" y="2" width="10" height="11" rx="1.5" stroke="currentColor" stroke-width="1.3" /><path d="M2 5v8.5A1.5 1.5 0 003.5 15H11" stroke="currentColor" stroke-width="1.3" /></svg>
          复制 Prompt
        </button>
        <button class="dbg-copy-btn" @click="copyRawResponse">
          <svg viewBox="0 0 16 16" fill="none" width="13" height="13"><rect x="5" y="2" width="10" height="11" rx="1.5" stroke="currentColor" stroke-width="1.3" /><path d="M2 5v8.5A1.5 1.5 0 003.5 15H11" stroke="currentColor" stroke-width="1.3" /></svg>
          复制 Raw Response
        </button>
      </div>
    </div>

    <div class="dbg-detail-scroll">
      <div class="dbg-meta-grid">
        <div class="dbg-meta-item">
          <span class="dbg-meta-label">阶段</span>
          <span class="dbg-meta-value">{{ trace.phase }}</span>
        </div>
        <div class="dbg-meta-item">
          <span class="dbg-meta-label">事件</span>
          <span class="dbg-meta-value">{{ eventLabel(trace.event) }}</span>
        </div>
        <div class="dbg-meta-item">
          <span class="dbg-meta-label">模型</span>
          <span class="dbg-meta-value mono">{{ trace.model || '-' }}</span>
        </div>
        <div class="dbg-meta-item">
          <span class="dbg-meta-label">Host</span>
          <span class="dbg-meta-value mono">{{ trace.baseUrlHost || '-' }}</span>
        </div>
        <div v-if="trace.latencyMs != null" class="dbg-meta-item">
          <span class="dbg-meta-label">耗时</span>
          <span class="dbg-meta-value">{{ (trace.latencyMs / 1000).toFixed(2) }}s</span>
        </div>
        <div class="dbg-meta-item">
          <span class="dbg-meta-label">时间</span>
          <span class="dbg-meta-value">{{ formatTime(trace.timestamp) }}</span>
        </div>
        <div v-if="tokenUsage?.prompt_tokens != null" class="dbg-meta-item">
          <span class="dbg-meta-label">Prompt Tokens</span>
          <span class="dbg-meta-value mono">{{ tokenUsage.prompt_tokens }}</span>
        </div>
        <div v-if="tokenUsage?.completion_tokens != null" class="dbg-meta-item">
          <span class="dbg-meta-label">Completion Tokens</span>
          <span class="dbg-meta-value mono">{{ tokenUsage.completion_tokens }}</span>
        </div>
      </div>

      <div v-if="trace.error" class="dbg-alert dbg-alert-error">
        <svg viewBox="0 0 20 20" fill="none" width="16" height="16"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4" /><path d="M10 6v4.5M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" /></svg>
        <span>{{ trace.error }}</span>
      </div>
      <div v-if="trace.parseError" class="dbg-alert dbg-alert-warning">
        <svg viewBox="0 0 20 20" fill="none" width="16" height="16"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4" /><path d="M10 6v4.5M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" /></svg>
        <span>解析失败：{{ trace.parseError }}</span>
      </div>

      <DebugCodeSection title="System Prompt" :content="systemPrompt" @copy="copyText" />
      <DebugCodeSection title="Input Payload" :content="inputPayloadStr" @copy="copyText" />
      <DebugCodeSection title="Raw Response" :content="trace.rawResponse ?? ''" @copy="copyText" />
      <DebugCodeSection title="Parsed Result" :content="parsedResultStr" @copy="copyText" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { ElMessage } from "element-plus";
import type { LLMTraceRecord } from "../../../types";
import { errorMessage } from "../../../utils";
import DebugCodeSection from "./DebugCodeSection.vue";
import { eventLabel, formatTime } from "./traceFormat";

const props = defineProps<{ trace: LLMTraceRecord }>();

const systemPrompt = computed(() => props.trace.systemPrompt || "");
const tokenUsage = computed(() => props.trace.tokenUsage || null);
const inputPayloadStr = computed(() => {
  const payload = props.trace.inputPayload;
  if (!payload) return "";
  return JSON.stringify(payload, null, 2);
});
const parsedResultStr = computed(() => {
  const result = props.trace.parsedResult;
  if (result == null) return "";
  return JSON.stringify(result, null, 2);
});

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    ElMessage({ message: "已复制到剪贴板", type: "success", duration: 1500 });
  } catch (caught) {
    ElMessage({ message: errorMessage(caught) || "复制失败", type: "error", duration: 2000 });
  }
}

function copyPrompt() {
  let text = systemPrompt.value;
  if (inputPayloadStr.value) {
    text += "\n\n--- Input ---\n" + inputPayloadStr.value;
  }
  copyText(text);
}

function copyRawResponse() {
  if (!props.trace.rawResponse) return;
  copyText(props.trace.rawResponse);
}
</script>

<style scoped>
.dbg-detail {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dbg-detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 11px 18px;
  border-bottom: 1px solid var(--line-soft, #e4e7ed);
  flex-shrink: 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.7) 0%, rgba(255, 255, 255, 0.4) 100%);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.dbg-detail-title {
  font-weight: 700;
  font-size: 16px;
  color: var(--text-strong, #11181c);
  letter-spacing: -0.005em;
}

.dbg-detail-actions {
  display: flex;
  gap: 6px;
}

.dbg-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-xs, 6px);
  background: rgba(255, 255, 255, 0.6);
  color: var(--text-muted, #4b5563);
  font-size: 14px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.dbg-copy-btn:hover {
  background: var(--brand-50, #f4f3ff);
  color: var(--brand-600, #4f46e5);
  border-color: var(--brand-100, #e0e7ff);
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.12);
}

.dbg-detail-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: transparent;
}

.dbg-detail-scroll > * {
  flex-shrink: 0;
}

.dbg-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1px;
  background: var(--line-soft, #e4e7ed);
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-sm, 10px);
  overflow: hidden;
  flex-shrink: 0;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.dbg-meta-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 11px 14px;
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.dbg-meta-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-faint, #6b7280);
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.dbg-meta-value {
  font-size: 14px;
  color: var(--text-strong, #11181c);
  word-break: break-word;
}

.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 13px;
}

.dbg-alert {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 14px;
  border-radius: var(--radius-sm, 10px);
  font-size: 15px;
  line-height: 1.4;
  flex-shrink: 0;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.dbg-alert svg {
  margin-top: 2px;
  flex-shrink: 0;
}

.dbg-alert-error {
  background: linear-gradient(135deg, rgba(255, 241, 242, 0.9) 0%, rgba(255, 255, 255, 0.7) 100%);
  border: 1px solid #fecdd3;
  color: var(--danger, #b42318);
}

.dbg-alert-warning {
  background: linear-gradient(135deg, rgba(255, 250, 235, 0.9) 0%, rgba(255, 255, 255, 0.7) 100%);
  border: 1px solid #fde68a;
  color: var(--warning, #b54708);
}
</style>
