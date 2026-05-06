<template>
  <section class="panel">
    <h2 class="panel-header">
      <span>模型列表</span>
      <button class="primary" type="button" @click="openNewModelDialog">新增模型</button>
    </h2>
    <ModelTable
        :models="models"
        @edit="editModel"
        @test="testModel"
        @delete="deleteModel"
    />
  </section>

  <div v-if="showModelDialog" class="dialog-backdrop">
    <div class="dialog wide" role="dialog" aria-modal="true">
      <div class="dialog-header">
        <h2>{{ modelForm.editingId ? '编辑模型' : '新增模型' }}</h2>
        <button type="button" aria-label="关闭" @click="closeModelDialog">×</button>
      </div>
      <form @submit.prevent="saveModel">
        <div class="dialog-body">
          <div v-if="error" class="banner error dialog-error">{{ error }}</div>
          <div class="form-grid">
            <div class="field" :class="{'has-error': formErrors.modelName}">
              <label>名称</label>
              <input v-model="modelForm.name" @input="delete formErrors.modelName"/>
              <div v-if="formErrors.modelName" class="field-error">{{ formErrors.modelName }}</div>
            </div>
            <div class="form-grid two">
              <div class="field">
                <label>供应商</label>
                <select v-model="modelForm.provider">
                  <option v-for="provider in providers" :key="provider" :value="provider">
                    {{ provider }}
                  </option>
                </select>
              </div>
              <div class="field" :class="{'has-error': formErrors.modelModel}">
                <label>模型</label>
                <input v-model="modelForm.model" required @input="delete formErrors.modelModel"/>
                <div v-if="formErrors.modelModel" class="field-error">{{ formErrors.modelModel }}</div>
              </div>
            </div>
            <div class="field">
              <label>API Key</label>
              <input v-model="modelForm.apiKey" type="password" autocomplete="new-password"/>
            </div>
            <div class="field">
              <label>Base URL</label>
              <input v-model="modelForm.baseUrl"/>
            </div>
            <div class="field">
              <label>Completions Path</label>
              <input v-model="modelForm.completionsPath"/>
            </div>
            <div class="form-grid two">
              <div class="field">
                <label>最大 Token</label>
                <input v-model="modelForm.maxTokens" type="number" min="1"/>
              </div>
              <div class="field">
                <label>温度</label>
                <input v-model="modelForm.temperature" type="number" min="0" step="0.01"/>
              </div>
            </div>
            <div class="form-grid two">
              <div class="field">
                <label>重试次数</label>
                <input v-model="modelForm.maxRetries" type="number" min="0"/>
              </div>
              <div class="field">
                <label>超时秒数</label>
                <input v-model="modelForm.timeoutSeconds" type="number" min="1"/>
              </div>
            </div>
            <div class="field">
              <label>任务类型默认</label>
              <select v-model="modelForm.taskType">
                <option value="">全局默认</option>
                <option value="blackbox">blackbox</option>
                <option value="whitebox">whitebox</option>
              </select>
            </div>
            <div class="checks">
              <label><input v-model="modelForm.isDefault" type="checkbox"/> 默认</label>
              <label><input v-model="modelForm.enabled" type="checkbox"/> 启用</label>
            </div>
          </div>
        </div>
        <div class="dialog-actions">
          <button class="primary" type="submit">{{ modelForm.editingId ? '保存' : '创建' }}</button>
          <button type="button" @click="testModel(modelForm.editingId ?? '')">测试</button>
          <button type="button" @click="closeModelDialog">取消</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import ModelTable from "../components/ModelTable.vue";
import { useConsoleApp } from "../composables/useConsoleApp";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const {
  models, modelForm, showModelDialog, formErrors, error, providers,
  editModel, testModel, deleteModel, saveModel, openNewModelDialog,
} = props.app;

function closeModelDialog(): void {
  showModelDialog.value = false;
}
</script>
