<template>
  <template v-if="view === 'task-detail'">
    <div class="report-bar">
      <button type="button" @click="goBackToTasks">← 返回任务列表</button>
      <a
          v-if="selectedTask"
          :href="reportUrl(selectedTask.taskId)"
          target="_blank"
          rel="noreferrer"
      >
        <button type="button">在新标签页打开</button>
      </a>
    </div>
    <div v-if="!selectedTask" class="empty">未选择任务</div>
    <ReportView
        v-else
        :report="reportData"
        :loading="reportLoading"
        :task-id="selectedTask.taskId"
    />
  </template>
  <template v-else>
    <section class="panel">
      <h2 class="panel-header">
        <span>任务列表</span>
        <button class="primary" type="button" @click="openNewTaskDialog">新增任务</button>
      </h2>
      <div class="actions filter-actions">
        <select v-model="taskStatusFilter">
          <option value="">全部状态</option>
          <option v-for="status in taskStatuses" :key="status" :value="status">
            {{ status }}
          </option>
        </select>
        <select v-model="taskProjectFilter">
          <option value="">全部项目</option>
          <option
              v-for="project in projects"
              :key="project.projectId"
              :value="project.projectId"
          >
            {{ project.name }}
          </option>
        </select>
      </div>
      <TaskTable
          :tasks="visibleTasks"
          :projects="projects"
          @select="selectTask"
          @start="startTask"
      />
    </section>
  </template>

  <div v-if="showTaskDialog" class="dialog-backdrop">
    <div class="dialog wide" role="dialog" aria-modal="true">
      <div class="dialog-header">
        <h2>创建任务</h2>
        <button type="button" aria-label="关闭" @click="closeTaskDialog">×</button>
      </div>
      <form @submit.prevent="saveTask">
        <div class="dialog-body">
          <div v-if="error" class="banner error dialog-error">{{ error }}</div>
          <div class="form-grid">
            <div class="field">
              <label>项目</label>
              <select v-model="taskForm.projectId" required>
                <option
                    v-for="project in projects"
                    :key="project.projectId"
                    :value="project.projectId"
                >
                  {{ project.name }}
                </option>
              </select>
            </div>
            <div class="field" :class="{'has-error': formErrors.goal}">
              <label>目标</label>
              <textarea v-model="taskForm.goal" @input="delete formErrors.goal"></textarea>
              <div v-if="formErrors.goal" class="field-error">{{ formErrors.goal }}</div>
            </div>
            <div class="field">
              <label>起始 URL</label>
              <input v-model="taskForm.startUrl"/>
            </div>
            <div class="form-grid two">
              <div class="field">
                <label>最大步骤</label>
                <input v-model="taskForm.maxSteps" type="number" min="1"/>
              </div>
              <div class="field">
                <label>超时秒数</label>
                <input v-model="taskForm.timeoutSeconds" type="number" min="1"/>
              </div>
            </div>
            <div class="field">
              <label>模型配置</label>
              <select v-model="taskForm.modelConfigId">
                <option value="">默认模型</option>
                <option
                    v-for="model in enabledModels"
                    :key="model.modelConfigId"
                    :value="model.modelConfigId"
                >
                  {{ model.name }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>截图</label>
              <select v-model="taskForm.captureScreenshots">
                <option value="">使用项目默认</option>
                <option value="true">开启</option>
                <option value="false">关闭</option>
              </select>
            </div>
            <div class="field" :class="{'has-error': formErrors.taskParameters}">
              <label>参数 JSON</label>
              <textarea v-model="taskForm.parameters" @input="delete formErrors.taskParameters"></textarea>
              <div v-if="formErrors.taskParameters" class="field-error">{{ formErrors.taskParameters }}</div>
            </div>
          </div>
        </div>
        <div class="dialog-actions">
          <button class="primary" type="submit">创建</button>
          <button type="button" @click="closeTaskDialog">取消</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import TaskTable from "../components/TaskTable.vue";
import ReportView from "./ReportView.vue";
import { reportUrl } from "../api";
import { useConsoleApp } from "../composables/useConsoleApp";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const {
  view, projects, visibleTasks, taskStatusFilter, taskProjectFilter,
  taskStatuses, selectedTask, reportData, reportLoading, taskForm,
  showTaskDialog, formErrors, error, enabledModels,
  selectTask, startTask, goBackToTasks, saveTask, openNewTaskDialog,
} = props.app;

function closeTaskDialog(): void {
  showTaskDialog.value = false;
}
</script>
