<template>
  <el-dialog
    :model-value="visible"
    title="项目详情"
    width="620px"
    align-center
    append-to-body
    :close-on-click-modal="false"
    @update:model-value="$emit('close')"
  >
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
          <template v-if="Object.keys(restParameters).length">
            <div v-for="(val, key) in restParameters" :key="key" class="detail-param">
              <span class="detail-param-key">{{ key }}</span>
              <span class="detail-param-val">{{
                typeof val === "string" ? val : JSON.stringify(val)
              }}</span>
            </div>
          </template>
          <span v-else>-</span>
        </span>
      </div>
      <div v-if="hasExt" class="detail-row">
        <span class="detail-label">Prompt 扩展</span>
        <span class="detail-value">
          <PromptExtensionViewer :extensions="promptExtensions" />
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
import { computed, defineAsyncComponent } from "vue";
import type { Project } from "../../types";
import { formatDate } from "../../utils";
import {
  emptyPromptExtensions,
  hasAnyExtension,
  splitParametersFromPromptExtensions,
} from "../../promptExtensions";
import "../../styles/detail-grid.css";

// 懒加载：markdown-it + dompurify 依赖随该组件异步加载，
// 避免在详情打开前就拉取 vendor-markdown chunk。
const PromptExtensionViewer = defineAsyncComponent(
  () => import("../prompt/PromptExtensionViewer.vue"),
);

const props = defineProps<{ visible: boolean; project: Project | null }>();
defineEmits<{ close: [] }>();

const split = computed(() => {
  if (!props.project) {
    return { rest: {} as Record<string, unknown>, promptExtensions: emptyPromptExtensions() };
  }
  return splitParametersFromPromptExtensions(props.project.parameters);
});

const restParameters = computed(() => split.value.rest);
const promptExtensions = computed(() => split.value.promptExtensions);
const hasExt = computed(() => hasAnyExtension(promptExtensions.value));
</script>
