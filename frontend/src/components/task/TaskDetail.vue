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
  gap: 12px;
}

.detail-row {
  display: flex;
  align-items: flex-start;
}

.detail-label {
  flex: 0 0 120px;
  color: #909399;
  font-size: 14px;
  line-height: 1.8;
}

.detail-value {
  flex: 1;
  font-size: 14px;
  line-height: 1.8;
  word-break: break-all;
}

.detail-value.mono {
  font-family: "SF Mono", "Cascadia Code", "Menlo", monospace;
  font-size: 13px;
}

.detail-param {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
}

.detail-param-key {
  font-weight: 600;
  min-width: 80px;
}

.detail-param-val {
  color: #606266;
}
</style>
