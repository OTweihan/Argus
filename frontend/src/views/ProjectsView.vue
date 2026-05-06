<template>
  <section class="panel">
    <h2 class="panel-header">
      <span>项目列表</span>
      <button class="primary" type="button" @click="openNewProjectDialog">新增项目</button>
    </h2>
    <ProjectTable :projects="projects" @edit="editProject" @delete="deleteProject"/>
  </section>

  <div v-if="showProjectDialog" class="dialog-backdrop">
    <div class="dialog wide" role="dialog" aria-modal="true">
      <div class="dialog-header">
        <h2>{{ projectForm.editingId ? '编辑项目' : '新增项目' }}</h2>
        <button type="button" aria-label="关闭" @click="closeProjectDialog">×</button>
      </div>
      <form @submit.prevent="saveProject">
        <div class="dialog-body">
          <div v-if="error" class="banner error dialog-error">{{ error }}</div>
          <div class="form-grid">
            <div class="field" :class="{'has-error': formErrors.name}">
              <label>名称</label>
              <input v-model="projectForm.name" @input="delete formErrors.name"/>
              <div v-if="formErrors.name" class="field-error">{{ formErrors.name }}</div>
            </div>
            <div class="field">
              <label>描述</label>
              <textarea v-model="projectForm.description"></textarea>
            </div>
            <div class="field">
              <label>基础 URL</label>
              <input v-model="projectForm.baseUrl" placeholder="https://example.com"/>
            </div>
            <div class="field">
              <label>Git URL</label>
              <input v-model="projectForm.gitUrl"/>
            </div>
            <div class="field">
              <label>登录态名称</label>
              <input v-model="projectForm.authStateName"/>
            </div>
            <div class="form-grid two">
              <div class="field">
                <label>默认最大步骤</label>
                <input v-model="projectForm.defaultMaxSteps" type="number" min="1"/>
              </div>
              <div class="field">
                <label>默认超时秒数</label>
                <input v-model="projectForm.defaultTimeoutSeconds" type="number" min="1"/>
              </div>
            </div>
            <div class="checks">
              <label>
                <input v-model="projectForm.defaultCaptureScreenshots" type="checkbox"/>
                截图
              </label>
            </div>
            <div class="field" :class="{'has-error': formErrors.projectParameters}">
              <label>参数 JSON</label>
              <textarea v-model="projectForm.parameters" @input="delete formErrors.projectParameters"></textarea>
              <div v-if="formErrors.projectParameters" class="field-error">{{ formErrors.projectParameters }}</div>
            </div>
          </div>
        </div>
        <div class="dialog-actions">
          <button class="primary" type="submit">{{ projectForm.editingId ? '保存' : '创建' }}</button>
          <button type="button" @click="closeProjectDialog">取消</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import ProjectTable from "../components/ProjectTable.vue";
import { useConsoleApp } from "../composables/useConsoleApp";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const {
  projects, projectForm, showProjectDialog, formErrors, error,
  editProject, deleteProject, saveProject, openNewProjectDialog,
} = props.app;

function closeProjectDialog(): void {
  showProjectDialog.value = false;
}
</script>
