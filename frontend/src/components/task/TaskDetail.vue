<template>
  <div class="detail-grid">
    <div class="detail-row">
      <span class="detail-label">项目</span>
      <span class="detail-value">{{ projectName }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">任务名称</span>
      <span class="detail-value">{{ displayTaskName(task) }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">任务类型</span>
      <span class="detail-value">
        <el-tag :type="task.taskType === 'whitebox' ? 'success' : 'info'" size="small">
          {{ task.taskType === "whitebox" ? "白盒分析" : "黑盒测试" }}
        </el-tag>
      </span>
    </div>
    <div class="detail-row">
      <span class="detail-label">目标</span>
      <span class="detail-value">{{ task.goal }}</span>
    </div>

    <!-- 黑盒专属 -->
    <template v-if="task.taskType !== 'whitebox'">
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
        <span class="detail-label">截图</span>
        <span class="detail-value">{{ task.captureScreenshots ? "开启" : "关闭" }}</span>
      </div>
    </template>

    <!-- 白盒专属 -->
    <template v-if="task.taskType === 'whitebox'">
      <div class="detail-row">
        <span class="detail-label">源码来源</span>
        <span class="detail-value">{{ whiteboxSourceLabel }}</span>
      </div>
      <div v-if="whiteboxSourcePath" class="detail-row">
        <span class="detail-label">源码路径</span>
        <span class="detail-value mono">{{ whiteboxSourcePath }}</span>
      </div>
      <div v-if="whiteboxRef" class="detail-row">
        <span class="detail-label">分支/Ref</span>
        <span class="detail-value mono">{{ whiteboxRef }}</span>
      </div>
      <div v-if="whiteboxScope" class="detail-row">
        <span class="detail-label">分析范围</span>
        <span class="detail-value">{{ whiteboxScope }}</span>
      </div>
      <div v-if="whiteboxModules.length" class="detail-row">
        <span class="detail-label">目标模块</span>
        <span class="detail-value mono">{{ whiteboxModules.join(", ") }}</span>
      </div>
    </template>

    <div class="detail-row">
      <span class="detail-label">模型配置</span>
      <span class="detail-value">{{ modelName }}</span>
    </div>
    <div v-if="task.taskType !== 'whitebox'" class="detail-row">
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
    <div v-if="hasExt && task.taskType !== 'whitebox'" class="detail-row">
      <span class="detail-label">Prompt 扩展</span>
      <span class="detail-value">
        <PromptExtensionViewer :extensions="promptExtensions" />
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent } from "vue";
import type { ModelConfig, Project, Task } from "../../types";
import {
  hasAnyExtension,
  PROMPT_EXTENSIONS_KEY,
  splitParametersFromPromptExtensions,
} from "../../promptExtensions";
import { displayTaskName } from "../../utils";
import { stringifyParamValue } from "../../params";
import "../../styles/detail-grid.css";

// 懒加载：markdown-it + dompurify 依赖随该组件异步加载，
// 避免 Dashboard 首屏（TaskDetailDialog 链）就拉取 vendor-markdown chunk。
const PromptExtensionViewer = defineAsyncComponent(
  () => import("../prompt/PromptExtensionViewer.vue"),
);

const props = defineProps<{ task: Task; projects: Project[]; enabledModels: ModelConfig[] }>();

const projectName = computed(() => {
  if (!props.task.projectId) return "-";
  return (
    props.projects.find((project) => project.projectId === props.task.projectId)?.name ??
    props.task.projectId
  );
});

const modelConfigId = computed(() => props.task.parameters?.modelConfigId as string | undefined);
const modelName = computed(() => {
  const id = modelConfigId.value;
  if (!id) return "默认模型";
  return props.enabledModels.find((model) => model.modelConfigId === id)?.name ?? id;
});

const split = computed(() => splitParametersFromPromptExtensions(props.task.parameters));
const promptExtensions = computed(() => split.value.promptExtensions);
const hasExt = computed(() => hasAnyExtension(promptExtensions.value));

const parameterEntries = computed(() =>
  Object.entries(split.value.rest).filter(
    ([key]) => key !== "modelConfigId" && key !== PROMPT_EXTENSIONS_KEY,
  ),
);

// ── 白盒配置展示 ──
const whiteboxConfig = computed(() => props.task.whiteboxConfigView?.config);
const whiteboxSourceLabel = computed(() => {
  const cfg = whiteboxConfig.value;
  if (!cfg) return "-";
  return cfg.sourceType === "git" ? "Git 仓库" : "本地目录";
});
const whiteboxSourcePath = computed(() => {
  const cfg = whiteboxConfig.value;
  if (!cfg) return "";
  return cfg.sourceType === "git" ? cfg.repoUrlDisplay || "-" : cfg.sourcePathDisplay || "-";
});
const whiteboxRef = computed(() => {
  return whiteboxConfig.value?.ref || "";
});
const whiteboxScope = computed(() => {
  const s = whiteboxConfig.value?.scope;
  if (!s) return "";
  const labels: Record<string, string> = {
    all: "全量分析",
    changed: "增量分析",
    modules: "指定模块",
    endpoints: "仅端点提取",
    callgraph: "仅调用关系",
    flows: "调用关系 + 执行流",
    clusters: "调用关系 + 功能聚类",
  };
  return labels[s.toLowerCase()] || s;
});
const whiteboxModules = computed(() => {
  return whiteboxConfig.value?.targetModules || [];
});

function formatParamValue(value: unknown): string {
  return stringifyParamValue(value);
}
</script>
