<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('close')" title="项目详情" width="620px" append-to-body>
    <div v-if="project" class="detail-grid">
      <div class="detail-row">
        <span class="detail-label">名称</span>
        <span class="detail-value">{{ project.name }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">ID</span>
        <span class="detail-value mono">{{ project.projectId }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">描述</span>
        <span class="detail-value">{{ project.description ?? "-" }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">基础 URL</span>
        <span class="detail-value mono">{{ project.baseUrl ?? "-" }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Git URL</span>
        <span class="detail-value mono">{{ project.gitUrl ?? "-" }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">认证状态</span>
        <span class="detail-value">{{ project.authStateName ?? "-" }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">默认最大步骤</span>
        <span class="detail-value">{{ project.defaultMaxSteps ?? "-" }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">默认超时（秒）</span>
        <span class="detail-value">{{ project.defaultTimeoutSeconds ?? "-" }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">默认截图</span>
        <span class="detail-value">{{ project.defaultCaptureScreenshots ? "开启" : "关闭" }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">参数</span>
        <span class="detail-value">
          <template v-if="Object.keys(project.parameters).length">
            <div v-for="(val, key) in project.parameters" :key="key" class="detail-param">
              <span class="detail-param-key">{{ key }}</span>
              <span class="detail-param-val">{{ typeof val === "string" ? val : JSON.stringify(val) }}</span>
            </div>
          </template>
          <span v-else>-</span>
        </span>
      </div>
      <div class="detail-row">
        <span class="detail-label">创建时间</span>
        <span class="detail-value">{{ formatDate(project.createdAt) }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">更新时间</span>
        <span class="detail-value">{{ formatDate(project.updatedAt) }}</span>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import type {Project} from "../../types";
import {formatDate} from "../../utils";

defineProps<{ visible: boolean; project: Project | null }>();
defineEmits<{ close: [] }>();
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
