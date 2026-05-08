<template>
  <div class="projects-wrapper">
    <el-card class="projects-card">
      <template #header>
        <div class="card-header">
          <span>项目列表</span>
          <el-button type="primary" @click="openNewProjectDialog">新增项目</el-button>
        </div>
      </template>
      <div class="filter-bar">
        <el-input v-model="searchQuery" placeholder="搜索名称、基础 URL" clearable class="search-input">
          <template #prefix>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
                 stroke-linejoin="round" class="search-icon">
              <circle cx="11" cy="11" r="8"/>
              <path d="m21 21-4.35-4.35"/>
            </svg>
          </template>
        </el-input>
      </div>
      <div class="table-wrap">
        <ProjectTable :projects="filteredProjects" height="100%" @detail="showDetail" @edit="editProject"
                      @delete="deleteProject"/>
      </div>
    </el-card>

    <ProjectFormDialog
        :visible="showProjectDialog"
        :form="projectForm"
        :editing="Boolean(projectForm.editingId)"
        :form-errors="formErrors"
        @save="saveProject"
        @close="showProjectDialog = false"
        @add-param="projectForm.parameters.push({key:'', value:''})"
        @remove-param="projectForm.parameters.splice($event, 1)"
    />

    <ProjectDetailDialog
        :visible="detailVisible"
        :project="detailProject"
        @close="detailVisible = false"
    />
  </div>
</template>

<script setup lang="ts">
import {computed, ref} from "vue";
import type {Project} from "../types";
import ProjectTable from "../components/project/ProjectTable.vue";
import ProjectFormDialog from "../components/project/ProjectFormDialog.vue";
import ProjectDetailDialog from "../components/project/ProjectDetailDialog.vue";
import {useConsoleApp} from "../composables/useConsoleApp";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const {
  projects, projectForm, showProjectDialog, formErrors,
  editProject, deleteProject, saveProject, openNewProjectDialog,
} = props.app;

const searchQuery = ref("");
const detailVisible = ref(false);
const detailProject = ref<Project | null>(null);

function showDetail(project: Project): void {
  detailProject.value = project;
  detailVisible.value = true;
}

const filteredProjects = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  const list = projects.value;
  if (!q) return list;
  return list.filter(
      (p) =>
          p.name.toLowerCase().includes(q) ||
          p.projectId.toLowerCase().includes(q) ||
          (p.description ?? "").toLowerCase().includes(q) ||
          (p.baseUrl ?? "").toLowerCase().includes(q) ||
          (p.gitUrl ?? "").toLowerCase().includes(q) ||
          (p.authStateName ?? "").toLowerCase().includes(q),
  );
});
</script>

<style scoped>
.projects-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.projects-card {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

:deep(.projects-card .el-card__body) {
  flex: 1;
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

.table-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
</style>
