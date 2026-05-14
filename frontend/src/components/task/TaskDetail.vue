<template>
  <div class="detail-grid">
    <div class="detail-row">
      <span class="detail-label">项目</span>
      <span class="detail-value">{{ projectName }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">任务名称</span>
      <span class="detail-value">{{ task.name || "-" }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">目标</span>
      <span class="detail-value">{{ task.goal }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">起始 URL</span>
      <span class="detail-value mono">{{ task.startUrl || "-" }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">最大步骤</span>
      <span class="detail-value">{{ task.maxSteps }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">超时秒数</span>
      <span class="detail-value">{{ task.timeoutSeconds }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">模型配置</span>
      <span class="detail-value">{{ modelName }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">截图</span>
      <span class="detail-value">{{ task.captureScreenshots ? "开启" : "关闭" }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">参数</span>
      <span class="detail-value">
        <template v-if="parameterEntries.length">
          <div v-for="[key, value] in parameterEntries" :key="key" class="detail-param">
            <span class="detail-param-key">{{ key }}</span>
            <span class="detail-param-val">{{ formatParamValue(value) }}</span>
          </div>
        </template>
        <span v-else>-</span>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import {computed} from "vue";
import type {ModelConfig, Project, Task} from "../../types";

const props = defineProps<{ task: Task; projects: Project[]; enabledModels: ModelConfig[] }>();

const projectName = computed(() => {
  if (!props.task.projectId) return "-";
  return props.projects.find((project) => project.projectId === props.task.projectId)?.name ?? props.task.projectId;
});

const modelConfigId = computed(() => props.task.parameters?.modelConfigId as string | undefined);
const modelName = computed(() => {
  const id = modelConfigId.value;
  if (!id) return "默认模型";
  return props.enabledModels.find((model) => model.modelConfigId === id)?.name ?? id;
});

const parameterEntries = computed(() => Object.entries(props.task.parameters ?? {}).filter(([key]) => key !== "modelConfigId"));

function formatParamValue(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}
</script>

<style scoped>
.detail-grid {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 0;
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-md, 14px);
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  overflow: hidden;
}

.detail-row {
  display: flex;
  align-items: flex-start;
  padding: 10px 16px;
  gap: 12px;
}

.detail-row:not(:last-child) {
  border-bottom: 1px solid var(--line-soft, #e4e7ed);
}

.detail-label {
  flex: 0 0 110px;
  color: var(--text-faint, #6b7280);
  font-size: 13px;
  font-weight: 600;
  line-height: 1.7;
}

.detail-value {
  flex: 1;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-strong, #11181c);
  word-break: break-all;
}

.detail-value.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 13px;
  color: var(--text-base, #182125);
}

.detail-param {
  display: flex;
  gap: 10px;
  margin-bottom: 6px;
  padding: 6px 10px;
  border-radius: var(--radius-xs, 6px);
  background: rgba(244, 243, 255, 0.4);
}

.detail-param:last-child {
  margin-bottom: 0;
}

.detail-param-key {
  font-weight: 700;
  min-width: 80px;
  color: var(--brand-700, #4338ca);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 13px;
}

.detail-param-val {
  color: var(--text-base, #182125);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 13px;
  word-break: break-all;
}
</style>
