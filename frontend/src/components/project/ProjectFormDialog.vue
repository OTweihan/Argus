<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('close')"
             :title="editing ? '编辑项目' : '新增项目'" width="580px" align-center append-to-body>
    <el-form label-position="top" @submit.prevent="$emit('save')">
      <el-form-item label="名称" :error="formErrors.name" required>
        <el-input v-model="form.name" maxlength="50" @input="clearError('name')" show-word-limit/>
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="4" maxlength="200" show-word-limit/>
      </el-form-item>
      <el-form-item label="基础 URL" :error="formErrors.baseUrl">
        <el-input v-model="form.baseUrl" placeholder="https://example.com" @input="clearError('baseUrl')"/>
      </el-form-item>
      <el-form-item label="Git URL" :error="formErrors.gitUrl">
        <el-input v-model="form.gitUrl" placeholder="https://github.com/" @input="clearError('gitUrl')"/>
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="默认最大步骤">
            <el-input-number v-model="form.defaultMaxSteps" :min="1" :max="1000" :step="1" :precision="0"
                             style="width:100%"/>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="默认超时秒数">
            <el-input-number v-model="form.defaultTimeoutSeconds" :min="1" :max="3600" :step="1" :precision="0"
                             style="width:100%"/>
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="截图">
        <el-radio-group v-model="form.defaultCaptureScreenshots">
          <el-radio :value="true">开启</el-radio>
          <el-radio :value="false">关闭</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="参数" :error="formErrors.projectParameters">
        <div class="param-list">
          <div v-for="(entry, index) in form.parameters" :key="index" class="param-row">
            <el-input v-model="entry.key" placeholder="键名" class="param-key"
                      @input="clearError('projectParameters')"/>
            <el-input v-model="entry.value" placeholder="值（字符串）" class="param-value"
                      @input="clearError('projectParameters')"/>
            <el-button type="danger" circle @click="$emit('remove-param', index)">×</el-button>
          </div>
          <el-button class="param-add-btn" @click="$emit('add-param')">+ 添加参数</el-button>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('close')">取消</el-button>
      <el-button type="primary" @click="$emit('save')">{{ editing ? '保存' : '创建' }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import type {ProjectForm} from "../../composables/useProjects";

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

function clearError(key: string): void {
  delete (props.formErrors as Record<string, string | undefined>)[key];
}
</script>

<style scoped>
.param-list {
  width: 100%;
}

.param-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.param-key {
  flex: 2;
}

.param-value {
  flex: 3;
}

.param-add-btn {
  margin-top: 4px;
}
</style>
