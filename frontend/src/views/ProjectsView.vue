<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>项目列表</span>
        <el-button type="primary" @click="openNewProjectDialog">新增项目</el-button>
      </div>
    </template>
    <ProjectTable :projects="projects" @edit="editProject" @delete="deleteProject"/>
  </el-card>

  <el-dialog v-model="showProjectDialog" :title="projectForm.editingId ? '编辑项目' : '新增项目'" width="580px"
             append-to-body>
    <el-form :model="projectForm" label-position="top" @submit.prevent="saveProject">
      <el-form-item label="名称" :error="formErrors.name" required>
        <el-input v-model="projectForm.name" maxlength="50" @input="delete formErrors.name" show-word-limit/>
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="projectForm.description" type="textarea" :rows="4" maxlength="200" show-word-limit/>
      </el-form-item>
      <el-form-item label="基础 URL" :error="formErrors.baseUrl">
        <el-input v-model="projectForm.baseUrl" placeholder="https://example.com" @input="delete formErrors.baseUrl"/>
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="默认最大步骤">
            <el-input-number v-model="projectForm.defaultMaxSteps" :min="1" :max="1000" :step="1" :precision="0"
                             style="width:100%"/>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="默认超时秒数">
            <el-input-number v-model="projectForm.defaultTimeoutSeconds" :min="1" :max="3600" :step="1" :precision="0"
                             style="width:100%"/>
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="截图">
        <el-checkbox v-model="projectForm.defaultCaptureScreenshots">默认开启截图</el-checkbox>
      </el-form-item>
      <el-form-item label="参数 JSON" :error="formErrors.projectParameters">
        <el-input v-model="projectForm.parameters" type="textarea" :rows="3"
                  @input="delete formErrors.projectParameters"/>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="showProjectDialog = false">取消</el-button>
      <el-button type="primary" @click="saveProject">{{ projectForm.editingId ? '保存' : '创建' }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import ProjectTable from "../components/ProjectTable.vue";
import {useConsoleApp} from "../composables/useConsoleApp";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const {
  projects, projectForm, showProjectDialog, formErrors, error,
  editProject, deleteProject, saveProject, openNewProjectDialog,
} = props.app;
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
