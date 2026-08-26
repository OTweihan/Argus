<template>
  <el-dialog
    :model-value="store.showCaseDialog.value"
    :title="form.editingId ? '编辑回归用例' : '新建回归用例'"
    width="560px"
    append-to-body
    @update:model-value="onVisibilityChange"
  >
    <el-form label-width="110px" @submit.prevent>
      <el-form-item label="用例名称" required>
        <el-input v-model="form.name" placeholder="如：登录流程回归" maxlength="200" />
      </el-form-item>
      <el-form-item label="任务类型">
        <el-radio-group v-model="form.taskType" :disabled="Boolean(form.editingId)">
          <el-radio-button value="blackbox">黑盒</el-radio-button>
          <el-radio-button value="whitebox">白盒</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="测试目标" required>
        <el-input
          v-model="form.goal"
          type="textarea"
          :rows="2"
          placeholder="自然语言测试目标，保存时按任务创建规则校验"
        />
      </el-form-item>
      <template v-if="form.taskType === 'blackbox'">
        <el-form-item label="起始 URL">
          <el-input v-model="form.startUrl" placeholder="留空时使用项目 baseUrl" />
        </el-form-item>
        <el-form-item label="截图">
          <el-switch v-model="form.captureScreenshots" />
        </el-form-item>
      </template>
      <el-form-item label="最大步数">
        <el-input-number v-model="form.maxSteps" :min="1" :max="500" placeholder="留空使用默认" />
      </el-form-item>
      <el-form-item label="超时(秒)">
        <el-input-number
          v-model="form.timeoutSeconds"
          :min="1"
          :max="86400"
          placeholder="留空使用默认"
        />
      </el-form-item>
      <el-form-item label="执行参数">
        <el-input
          v-model="form.parametersText"
          type="textarea"
          :rows="4"
          placeholder="JSON 对象：model_config_id / prompt_extensions / 白盒 source_path 等"
        />
      </el-form-item>
      <el-form-item label="启用">
        <el-switch v-model="form.enabled" />
      </el-form-item>
      <el-form-item label="排序">
        <el-input-number v-model="form.displayOrder" :min="0" :max="10000" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('close')">取消</el-button>
      <el-button type="primary" :loading="saving" @click="emit('save')">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { RegressionStore } from "../../composables/useRegression";

const props = defineProps<{ store: RegressionStore }>();
const emit = defineEmits<{
  close: [];
  save: [];
}>();

// 解包 store 中 ref 的便捷访问（模板中统一 form.xxx）
const form = computed(() => props.store.caseForm.value);
const saving = computed(() => props.store.caseSaving.value);

function onVisibilityChange(visible: boolean): void {
  if (!visible) emit("close");
}
</script>
