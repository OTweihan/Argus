<template>
  <div class="models-wrapper">
    <el-card class="models-card">
      <template #header>
        <div class="card-header">
          <span>模型列表</span>
          <el-button type="primary" @click="openNewModelDialog">新增模型</el-button>
        </div>
      </template>
      <div class="filter-bar">
        <el-input v-model="modelSearchQuery" placeholder="搜索名称、供应商、模型、Base URL" clearable class="search-input">
          <template #prefix>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
                 stroke-linejoin="round" class="search-icon">
              <circle cx="11" cy="11" r="8"/>
              <path d="m21 21-4.35-4.35"/>
            </svg>
          </template>
        </el-input>
      </div>
      <ModelTable
        :models="filteredModels"
        height="100%"
        @edit="editModel"
        @test="testModel"
        @delete="deleteModel"
      />
    </el-card>
  </div>

  <el-dialog v-model="showModelDialog" :title="modelForm.editingId ? '编辑模型' : '新增模型'" width="580px" append-to-body>
    <el-form :model="modelForm" label-position="top" @submit.prevent="saveModel">
      <el-form-item label="名称" :error="formErrors.modelName" required>
        <el-input v-model="modelForm.name" @input="delete formErrors.modelName" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="供应商" required>
            <el-select v-model="modelForm.provider" style="width:100%">
              <el-option v-for="provider in providers" :key="provider" :label="provider" :value="provider" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="模型" :error="formErrors.modelModel" required>
            <el-input v-model="modelForm.model" @input="delete formErrors.modelModel" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="API Key">
        <el-input v-model="modelForm.apiKey" type="password" show-password autocomplete="new-password" />
      </el-form-item>
      <el-form-item label="Base URL">
        <el-input v-model="modelForm.baseUrl" />
      </el-form-item>
      <el-form-item label="Completions Path">
        <el-input v-model="modelForm.completionsPath" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="最大 Token">
            <el-input-number v-model="modelForm.maxTokens" :min="1" :step="1" :precision="0" style="width:100%" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="温度">
            <el-input-number v-model="modelForm.temperature" :min="0" :step="0.01" :precision="2" style="width:100%" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="重试次数">
            <el-input-number v-model="modelForm.maxRetries" :min="0" :step="1" :precision="0" style="width:100%" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="超时秒数">
            <el-input-number v-model="modelForm.timeoutSeconds" :min="1" :step="1" :precision="0" style="width:100%" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="任务类型默认">
        <el-select v-model="modelForm.taskType" clearable style="width:100%">
          <el-option label="全局默认" value="" />
          <el-option label="blackbox" value="blackbox" />
          <el-option label="whitebox" value="whitebox" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="modelForm.isDefault">默认</el-checkbox>
        <el-checkbox v-model="modelForm.enabled" style="margin-left: 16px">启用</el-checkbox>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="testModel(modelForm.editingId ?? '')">测试</el-button>
      <el-button @click="showModelDialog = false">取消</el-button>
      <el-button type="primary" @click="saveModel">{{ modelForm.editingId ? '保存' : '创建' }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import {computed, ref} from "vue";
import ModelTable from "../components/model/ModelTable.vue";
import { useConsoleApp } from "../composables/useConsoleApp";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const {
  models, modelForm, showModelDialog, formErrors, error, providers,
  editModel, testModel, deleteModel, saveModel, openNewModelDialog,
} = props.app;

const modelSearchQuery = ref("");

const filteredModels = computed(() => {
  const keyword = modelSearchQuery.value.trim().toLowerCase();
  const list = models.value;
  if (!keyword) return list;
  return list.filter((model) =>
    [
      model.name,
      model.provider,
      model.model,
      model.baseUrl,
      model.completionsPath,
      model.taskType ?? "",
      model.modelConfigId,
    ].some((value) => value.toLowerCase().includes(keyword)),
  );
});
</script>

<style scoped>
.models-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.models-card {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

:deep(.models-card .el-card__body) {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 0 20px 20px;
}

.card-header { display: flex; align-items: center; justify-content: space-between; }
.filter-bar { flex-shrink: 0; padding: 16px 0; }
.search-input { max-width: 360px; }
.search-icon { width: 16px; height: 16px; color: #909399; }
</style>
