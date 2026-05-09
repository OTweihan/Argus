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
import {useConsoleApp} from "../composables/useConsoleApp";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const {
  models, modelForm, showModelDialog, formErrors, error,
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

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.filter-bar {
  flex-shrink: 0;
  padding: 16px 0;
}

.search-input {
  max-width: 360px;
}

.search-icon {
  width: 16px;
  height: 16px;
  color: #909399;
}
</style>
