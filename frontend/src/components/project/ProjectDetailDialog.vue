<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('close')" title="项目详情" width="620px" align-center
             append-to-body>
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
