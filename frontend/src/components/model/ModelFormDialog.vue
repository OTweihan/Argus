<template>
  <el-dialog
    :model-value="visible"
    :title="editing ? '编辑模型' : '新增模型'"
    width="580px"
    align-center
    append-to-body
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    @update:model-value="$emit('close')"
  >
    <el-form :model="localForm" label-position="top" @submit.prevent="onSave">
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
        <el-input
          v-model="localForm.apiKey"
          type="password"
          show-password
          autocomplete="new-password"
        />
      </el-form-item>
      <el-form-item label="Base URL" :error="formErrors.modelBaseUrl" required>
        <el-input v-model="localForm.baseUrl" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="重试次数">
            <el-input-number
              v-model="localForm.maxRetries"
              :min="0"
              :step="1"
              :precision="0"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="超时秒数">
            <el-input-number
              v-model="localForm.timeoutSeconds"
              :min="1"
              :step="1"
              :precision="0"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="启用">
        <el-radio-group v-model="localForm.enabled">
          <el-radio :value="true"> 开启 </el-radio>
          <el-radio :value="false"> 关闭 </el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="默认">
        <el-radio-group v-model="localForm.isDefault">
          <el-radio :value="true"> 是 </el-radio>
          <el-radio :value="false"> 否 </el-radio>
        </el-radio-group>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button size="large" @click="onTest"> 测试 </el-button>
      <el-button size="large" @click="$emit('close')"> 取消 </el-button>
      <el-button size="large" type="primary" @click="onSave">
        {{ editing ? "保存" : "创建" }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, watch } from "vue";
import type { ModelForm } from "../../composables/useModels";

const props = defineProps<{
  visible: boolean;
  form: ModelForm;
  editing: boolean;
  formErrors: Record<string, string>;
}>();

const emit = defineEmits<{
  close: [];
  save: [];
  test: [];
}>();

const localForm = reactive<ModelForm>({ ...props.form });

// 打开时从父表单快照一次，替代原先整表 deep watch 的双向拷贝。
// 父级（useModels）在置 visible=true 之前已把 form 准备好。
watch(
  () => props.visible,
  (visible) => {
    if (visible) Object.assign(localForm, props.form);
  },
  { immediate: true },
);

// 父级也可能整体替换 form 引用（测试 setProps / 未来改造）：非 deep 监听引用变化。
watch(
  () => props.form,
  (f) => {
    if (f) Object.assign(localForm, f);
  },
);

// 保存时统一把顶层字段写回父表单。
function onSave(): void {
  Object.assign(props.form, localForm);
  emit("save");
}

// 测试连接前同样先把当前编辑写回父表单，使 testModel 读取的是弹窗内最新值。
function onTest(): void {
  Object.assign(props.form, localForm);
  emit("test");
}

function clearError(key: string): void {
  delete (props.formErrors as Record<string, string | undefined>)[key];
}
</script>
