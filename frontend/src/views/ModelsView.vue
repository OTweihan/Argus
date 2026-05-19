<template>
  <div class="models-wrapper">
    <el-card class="models-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">模型列表</span>
          <el-button type="primary" @click="openNewModelDialog">
            新增模型
          </el-button>
        </div>
      </template>
      <div class="filter-bar">
        <el-input v-model="modelSearchQuery" placeholder="搜索名称、供应商、模型、Base URL" clearable class="search-input">
          <template #prefix>
            <svg
              viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
              stroke-linejoin="round" class="search-icon"
            >
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
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

  <ModelFormDialog
    :visible="showModelDialog"
    :form="modelForm"
    :editing="Boolean(modelForm.editingId)"
    :form-errors="formErrors"
    @save="saveModel"
    @close="showModelDialog = false"
    @test="testModel(modelForm.editingId ?? '')"
  />
</template>

<script setup lang="ts">
import {computed, ref} from "vue";
import ModelTable from "../components/model/ModelTable.vue";
import ModelFormDialog from "../components/model/ModelFormDialog.vue";
import {injectConsoleApp} from "../composables/useConsoleApp";

const {
  models, modelForm, showModelDialog, formErrors,
  editModel, testModel, deleteModel, saveModel, openNewModelDialog,
} = injectConsoleApp();

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
  padding: 0 22px 22px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-title {
  position: relative;
  padding-left: 14px;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-strong);
  letter-spacing: -0.005em;
}

.card-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 18px;
  background-image: var(--brand-gradient);
  border-radius: 2px;
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.35);
}

.filter-bar {
  flex-shrink: 0;
  padding: 18px 0 14px;
  border-bottom: 1px solid var(--line-soft);
  margin-bottom: 6px;
}

.search-input {
  max-width: 360px;
}

.search-icon {
  width: 16px;
  height: 16px;
  color: var(--text-placeholder, #9ca3af);
}
</style>
