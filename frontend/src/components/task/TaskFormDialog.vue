<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('close')"
             :title="editing ? '编辑任务' : '创建任务'" width="580px" align-center append-to-body>
    <el-form :model="form" label-position="top" @submit.prevent="$emit('save')">
      <el-form-item label="项目" required>
        <el-select v-model="form.projectId" style="width:100%">
          <el-option v-for="project in projects" :key="project.projectId" :label="project.name"
                     :value="project.projectId"/>
        </el-select>
      </el-form-item>
      <el-form-item label="任务名称">
        <el-input v-model="form.name" maxlength="50" show-word-limit/>
      </el-form-item>
      <el-form-item label="目标" :error="formErrors.goal" required>
        <el-input v-model="form.goal" type="textarea" :rows="4" maxlength="200" show-word-limit
                  @input="clearError('goal')"/>
      </el-form-item>
      <el-form-item label="起始 URL" :error="formErrors.startUrl" required>
        <el-input v-model="form.startUrl" placeholder="https://example.com" @input="clearError('startUrl')"/>
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="最大步骤">
            <el-input-number v-model="form.maxSteps" :min="1" :step="1" :precision="0" style="width:100%"/>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="超时秒数">
            <el-input-number v-model="form.timeoutSeconds" :min="1" :step="1" :precision="0" style="width:100%"/>
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="模型配置">
        <el-select v-model="form.modelConfigId" style="width:100%">
          <el-option label="默认模型" value="__default__"/>
          <el-option v-for="model in enabledModels" :key="model.modelConfigId" :label="model.name"
                     :value="model.modelConfigId"/>
        </el-select>
      </el-form-item>
      <el-form-item label="截图">
        <el-select v-model="form.captureScreenshots" style="width:100%">
          <el-option label="使用项目默认" value="__default__"/>
          <el-option label="开启" value="true"/>
          <el-option label="关闭" value="false"/>
        </el-select>
      </el-form-item>
      <el-form-item label="参数" :error="formErrors.taskParameters">
        <div class="param-list">
          <div v-for="(entry, index) in form.parameters" :key="index" class="param-row">
            <el-input v-model="entry.key" placeholder="键名" class="param-key"
                      @input="clearError('taskParameters')"/>
            <el-input v-model="entry.value" placeholder="值（字符串）" class="param-value"/>
            <el-button type="danger" circle @click="$emit('remove-param', index)">×</el-button>
          </div>
          <el-button class="param-add-btn" @click="$emit('add-param')">+ 添加参数</el-button>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('close')">取消</el-button>
      <el-button type="primary" @click="$emit('save')">{{ editing ? "保存" : "创建" }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import type {ModelConfig, Project} from "../../types";

interface TaskForm {
  editingId: string | null;
  goal: string;
  name: string;
  projectId: string;
  startUrl: string;
  maxSteps: number | null;
  timeoutSeconds: number | null;
  captureScreenshots: string;
  modelConfigId: string;
  parameters: { key: string; value: string }[];
}

const props = defineProps<{
  visible: boolean;
  form: TaskForm;
  editing: boolean;
  formErrors: Record<string, string>;
  projects: Project[];
  enabledModels: ModelConfig[];
}>();

defineEmits<{
  close: [];
  save: [];
  "add-param": [];
  "remove-param": [index: number];
}>();

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
</style>
