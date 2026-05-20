<template>
  <el-dialog
    :model-value="visible" :title="editing ? '编辑模型' : '新增模型'"
    width="580px" align-center append-to-body @update:model-value="$emit('close')"
  >
    <el-form :model="localForm" label-position="top" @submit.prevent="$emit('save')">
      <el-form-item label="名称" :error="formErrors.modelName" required>
        <el-input v-model="localForm.name" @input="clearError('modelName')" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="供应商" :error="formErrors.modelProvider" required>
            <el-input v-model="localForm.provider" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="模型" :error="formErrors.modelModel" required>
            <el-input v-model="localForm.model" @input="clearError('modelModel')" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="API Key" :error="formErrors.modelApiKey" required>
        <el-input v-model="localForm.apiKey" type="password" show-password autocomplete="new-password" />
      </el-form-item>
      <el-form-item label="Base URL" :error="formErrors.modelBaseUrl" required>
        <el-input v-model="localForm.baseUrl" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="重试次数">
            <el-input-number v-model="localForm.maxRetries" :min="0" :step="1" :precision="0" style="width:100%" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="超时秒数">
            <el-input-number v-model="localForm.timeoutSeconds" :min="1" :step="1" :precision="0" style="width:100%" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="启用">
        <el-radio-group v-model="localForm.enabled">
          <el-radio :value="true">
            开启
          </el-radio>
          <el-radio :value="false">
            关闭
          </el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="默认">
        <el-radio-group v-model="localForm.isDefault">
          <el-radio :value="true">
            是
          </el-radio>
          <el-radio :value="false">
            否
          </el-radio>
        </el-radio-group>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('test')">
        测试
      </el-button>
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
import {reactive, watch} from "vue";

interface ModelForm {
  editingId: string | null;
  name: string;
  provider: string;
  model: string;
  apiKey: string;
  baseUrl: string;
  maxRetries: number | null;
  timeoutSeconds: number | null;
  isDefault: boolean;
  enabled: boolean;
}

const props = defineProps<{
  visible: boolean;
  form: ModelForm;
  editing: boolean;
  formErrors: Record<string, string>;
}>();

defineEmits<{
  close: [];
  save: [];
  test: [];
}>();

const localForm = reactive<ModelForm>({...props.form});

watch(localForm, () => {
  Object.assign(props.form, localForm);
}, {deep: true});

watch(() => props.form, (f) => {
  Object.assign(localForm, f);
}, {deep: true});

function clearError(key: string): void {
  delete (props.formErrors as Record<string, string | undefined>)[key];
}
</script>
