<template>
  <el-dialog
    :model-value="visible" :title="editing ? '编辑项目' : '新增项目'"
    width="800px" align-center append-to-body @update:model-value="$emit('close')"
  >
    <el-form label-position="top" @submit.prevent="$emit('save')">
      <el-form-item label="名称" :error="formErrors.name" required>
        <el-input v-model="form.name" maxlength="50" show-word-limit @input="clearError('name')" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="4" maxlength="200" show-word-limit />
      </el-form-item>
      <el-form-item label="基础 URL" :error="formErrors.baseUrl">
        <el-input v-model="form.baseUrl" placeholder="https://example.com" @input="clearError('baseUrl')" />
      </el-form-item>
      <el-form-item label="Git URL" :error="formErrors.gitUrl">
        <el-input v-model="form.gitUrl" placeholder="https://github.com/" @input="clearError('gitUrl')" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="默认最大步骤">
            <el-input-number
              v-model="form.defaultMaxSteps" :min="1" :max="1000" :step="1" :precision="0"
              style="width:100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="默认超时秒数">
            <el-input-number
              v-model="form.defaultTimeoutSeconds" :min="1" :max="3600" :step="1" :precision="0"
              style="width:100%"
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="截图">
        <el-radio-group v-model="form.defaultCaptureScreenshots">
          <el-radio :value="true">
            开启
          </el-radio>
          <el-radio :value="false">
            关闭
          </el-radio>
        </el-radio-group>
      </el-form-item>
      <el-collapse v-model="promptCollapseActive" class="prompt-collapse">
        <el-collapse-item name="prompt">
          <template #title>
            <span class="prompt-collapse-title">Prompt 业务扩展</span>
            <el-tag v-if="hasExt" size="small" type="success" effect="plain" class="prompt-collapse-tag">
              已配置
            </el-tag>
            <el-tag v-else size="small" type="info" effect="plain" class="prompt-collapse-tag">
              未配置
            </el-tag>
          </template>
          <PromptExtensionEditor v-model="form.promptExtensions" scope="project" />
        </el-collapse-item>
      </el-collapse>
      <el-form-item label="参数" :error="formErrors.projectParameters">
        <div class="param-list">
          <div v-for="(entry, index) in form.parameters" :key="index" class="param-row">
            <el-input
              v-model="entry.key" placeholder="键名" class="param-key"
              @input="clearError('projectParameters')"
            />
            <el-input
              v-model="entry.value" placeholder="值（字符串）" class="param-value"
              @input="clearError('projectParameters')"
            />
            <el-button type="danger" circle @click="$emit('remove-param', index)">
              ×
            </el-button>
          </div>
          <el-button class="param-add-btn" @click="$emit('add-param')">
            + 添加参数
          </el-button>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('close')">
        取消
      </el-button>
      <el-button type="primary" @click="$emit('save')">
        {{ editing ? '保存' : '创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import {computed, ref} from "vue";
import type {ProjectForm} from "../../composables/useProjects";
import {hasAnyExtension} from "../../promptExtensions";
import PromptExtensionEditor from "../prompt/PromptExtensionEditor.vue";

const props = defineProps<{
  visible: boolean;
  form: ProjectForm;
  editing: boolean;
  formErrors: Record<string, string>;
}>();

defineEmits<{
  close: [];
  save: [];
  "add-param": [];
  "remove-param": [index: number];
}>();

const promptCollapseActive = ref<string[]>([]);
const hasExt = computed(() => hasAnyExtension(props.form.promptExtensions));

function clearError(key: string): void {
  delete (props.formErrors as Record<string, string | undefined>)[key];
}
</script>

<style scoped>
.param-list {
  width: 100%;
  padding: 12px;
  border-radius: var(--radius-md);
  background: var(--surface-soft);
  border: 1px dashed var(--line-soft);
}

.param-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 10px;
}

.param-row:last-of-type {
  margin-bottom: 12px;
}

.param-key {
  flex: 2;
}

.param-value {
  flex: 3;
}

.param-add-btn {
  margin-top: 4px;
  width: 100%;
  border-style: dashed !important;
  color: var(--brand-600);
  border-color: var(--brand-100) !important;
  background: rgba(255, 255, 255, 0.6);
  font-weight: 540;
}

.param-add-btn:hover {
  color: #ffffff;
  background-image: var(--brand-gradient);
  border-color: transparent !important;
}

.prompt-collapse {
  margin-bottom: 18px;
  border-radius: var(--radius-md, 14px);
  overflow: hidden;
}

.prompt-collapse-title {
  font-weight: 600;
}

.prompt-collapse-tag {
  margin-left: 8px;
}
</style>
