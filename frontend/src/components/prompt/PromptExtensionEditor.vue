<template>
  <div class="prompt-extension-editor">
    <el-alert
      type="info" :closable="false" show-icon class="hint"
      title="项目/任务扩展会按顺序追加到内置 Prompt 末尾，仅供调试，安全边界仍以内置模板为准。"
    />
    <el-tabs v-model="activeRole" class="role-tabs">
      <el-tab-pane
        v-for="role in ROLES" :key="role.value" :label="role.label" :name="role.value"
      >
        <div class="split">
          <div class="split-col">
            <div class="col-title">
              编辑（Markdown）
            </div>
            <el-input
              :model-value="local[role.value]"
              type="textarea"
              :autosize="{minRows: 10, maxRows: 24}"
              :placeholder="role.placeholder"
              @update:model-value="onInput(role.value, $event)"
            />
          </div>
          <div class="split-col">
            <div class="col-title">
              预览
            </div>
            <div
              v-if="rendered[role.value]" class="md-preview"
              v-html="rendered[role.value]"
            />
            <div v-else class="md-preview placeholder">
              未填写扩展内容
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-collapse v-model="openPreviewPanes" class="full-preview-collapse">
      <el-collapse-item name="full" title="完整 system_prompt 预览（内置 + 项目 + 任务拼接）">
        <div v-if="previewError" class="preview-error">
          预览暂不可用：{{ previewError }}
        </div>
        <pre v-else-if="fullPreview" class="full-preview">{{ fullPreview }}</pre>
        <div v-else class="preview-loading">
          {{ previewLoading ? "正在计算预览…" : "切换 Tab 或输入内容后自动生成预览" }}
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
import {computed, onBeforeUnmount, reactive, ref, watch} from "vue";

import {previewPrompt} from "../../api";
import {useDebounceFn} from "../../composables/useDebounceFn";
import {renderMarkdown} from "../../composables/useMarkdown";
import {emptyPromptExtensions, type PromptExtensions, type PromptRole} from "../../promptExtensions";
import {errorMessage} from "../../utils";

const props = withDefaults(
  defineProps<{
    modelValue: PromptExtensions;
    scope: "project" | "task";
    projectExtensions?: PromptExtensions;
  }>(),
  {
    projectExtensions: () => emptyPromptExtensions(),
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: PromptExtensions];
}>();

const ROLES: ReadonlyArray<{
  value: PromptRole;
  label: string;
  placeholder: string;
}> = [
  {
    value: "planner",
    label: "Planner 扩展",
    placeholder: "用 Markdown 写入业务规则；例如：\n- 登录流程必须验证记住我复选框\n- 仅当出现退出登录按钮才视为登录成功",
  },
  {
    value: "evaluator",
    label: "Evaluator 扩展",
    placeholder: "用 Markdown 写入评估规则；例如：\n- 若结果出现连续多次重复尝试同一动作，应将完成度降级为部分完成",
  },
];

const activeRole = ref<PromptRole>("planner");
const local = reactive<PromptExtensions>({...props.modelValue});
const rendered = reactive<Record<PromptRole, string>>({
  planner: renderMarkdown(props.modelValue.planner),
  evaluator: renderMarkdown(props.modelValue.evaluator),
});

const fullPreview = ref<string>("");
const previewError = ref<string>("");
const previewLoading = ref(false);
const openPreviewPanes = ref<string[]>([]);

let previewRequestId = 0;

function onInput(role: PromptRole, value: string | number | null | undefined): void {
  const text = value === null || value === undefined ? "" : String(value);
  local[role] = text;
  rendered[role] = renderMarkdown(text);
  emit("update:modelValue", {...local});
}

const projectExtensionsForRequest = computed<PromptExtensions>(() => {
  if (props.scope === "task") {
    return props.projectExtensions ?? emptyPromptExtensions();
  }
  return emptyPromptExtensions();
});

async function refreshPreview(): Promise<void> {
  const ownExt = local[activeRole.value] ?? "";
  const projectExt = projectExtensionsForRequest.value[activeRole.value] ?? "";
  const taskExt = props.scope === "task" ? ownExt : "";
  const projectInput = props.scope === "project" ? ownExt : projectExt;

  if (!projectInput.trim() && !taskExt.trim()) {
    fullPreview.value = "";
    previewError.value = "";
    previewLoading.value = false;
    return;
  }

  const requestId = ++previewRequestId;
  previewLoading.value = true;
  previewError.value = "";
  try {
    const response = await previewPrompt({
      role: activeRole.value,
      projectExtension: projectInput,
      taskExtension: taskExt,
    });
    if (requestId !== previewRequestId) return;
    fullPreview.value = response.systemPrompt;
  } catch (err) {
    if (requestId !== previewRequestId) return;
    fullPreview.value = "";
    previewError.value = errorMessage(err);
  } finally {
    if (requestId === previewRequestId) previewLoading.value = false;
  }
}

const debouncedRefresh = useDebounceFn(refreshPreview, 600);

watch(
  () => [local.planner, local.evaluator, activeRole.value, props.projectExtensions?.planner, props.projectExtensions?.evaluator],
  () => debouncedRefresh(),
  {immediate: true},
);

watch(
  () => props.modelValue,
  (next) => {
    if (next.planner !== local.planner) {
      local.planner = next.planner ?? "";
      rendered.planner = renderMarkdown(local.planner);
    }
    if (next.evaluator !== local.evaluator) {
      local.evaluator = next.evaluator ?? "";
      rendered.evaluator = renderMarkdown(local.evaluator);
    }
  },
  {deep: true},
);

onBeforeUnmount(() => {
  debouncedRefresh.cancel();
});
</script>

<style scoped>
.prompt-extension-editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hint {
  font-size: 12px;
}

.role-tabs :deep(.el-tabs__nav) {
  font-weight: 600;
}

.split {
  display: flex;
  gap: 10px;
}

.split-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.col-title {
  font-size: 12px;
  color: var(--text-faint, #6b7280);
  font-weight: 600;
}

.md-preview {
  flex: 1;
  min-height: 180px;
  max-height: 360px;
  padding: 10px 12px;
  overflow-y: auto;
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-sm, 8px);
  background: var(--surface-soft, #fafbff);
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}

.md-preview.placeholder {
  color: var(--text-faint, #9aa1ad);
  display: flex;
  align-items: center;
  justify-content: center;
}

.md-preview :deep(p) {
  margin: 0 0 8px;
}

.md-preview :deep(ul),
.md-preview :deep(ol) {
  margin: 0 0 8px;
  padding-left: 20px;
}

.md-preview :deep(code) {
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(99, 102, 241, 0.08);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}

.md-preview :deep(pre) {
  margin: 0 0 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.04);
  overflow-x: auto;
}

.full-preview-collapse {
  border-radius: var(--radius-sm, 8px);
}

.full-preview {
  margin: 0;
  padding: 10px 12px;
  max-height: 320px;
  overflow: auto;
  background: rgba(15, 23, 42, 0.04);
  border-radius: var(--radius-sm, 8px);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.preview-error {
  padding: 10px 12px;
  color: var(--danger-600, #b91c1c);
  background: rgba(248, 113, 113, 0.08);
  border-radius: var(--radius-sm, 8px);
  font-size: 12px;
}

.preview-loading {
  padding: 10px 12px;
  color: var(--text-faint, #6b7280);
  font-size: 12px;
}
</style>
