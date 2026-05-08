<template>
  <template v-if="view === 'task-detail'">
    <div class="report-bar">
      <el-button @click="goBackToTasks">← 返回任务列表</el-button>
      <el-button v-if="selectedTask" @click="openReport">在新标签页打开</el-button>
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
    <el-card>
      <template #header>
        <div class="card-header">
          <span>任务列表</span>
          <el-button type="primary" @click="openNewTaskDialog">新增任务</el-button>
        </div>
      </template>
      <div class="filter-bar">
        <el-select v-model="taskStatusFilter" placeholder="全部状态" clearable style="width:140px">
          <el-option v-for="status in taskStatuses" :key="status" :label="status" :value="status" />
        </el-select>
        <el-select v-model="taskProjectFilter" placeholder="全部项目" clearable style="width:160px">
          <el-option v-for="project in projects" :key="project.projectId" :label="project.name" :value="project.projectId" />
        </el-select>
      </div>
      <TaskTable
        :tasks="visibleTasks"
        :projects="projects"
        @select="selectTask"
        @start="startTask"
      />
    </el-card>
  </template>

  <el-dialog v-model="showTaskDialog" title="创建任务" width="580px" append-to-body>
    <el-form :model="taskForm" label-position="top" @submit.prevent="saveTask">
      <el-form-item label="项目" required>
        <el-select v-model="taskForm.projectId" style="width:100%">
          <el-option v-for="project in projects" :key="project.projectId" :label="project.name" :value="project.projectId" />
        </el-select>
      </el-form-item>
      <el-form-item label="目标" :error="formErrors.goal" required>
        <el-input v-model="taskForm.goal" type="textarea" :rows="3" @input="delete formErrors.goal" />
      </el-form-item>
      <el-form-item label="起始 URL">
        <el-input v-model="taskForm.startUrl" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="最大步骤">
            <el-input-number v-model="taskForm.maxSteps" :min="1" :step="1" :precision="0" style="width:100%" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="超时秒数">
            <el-input-number v-model="taskForm.timeoutSeconds" :min="1" :step="1" :precision="0" style="width:100%" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="模型配置">
        <el-select v-model="taskForm.modelConfigId" clearable style="width:100%">
          <el-option label="默认模型" value="" />
          <el-option v-for="model in enabledModels" :key="model.modelConfigId" :label="model.name" :value="model.modelConfigId" />
        </el-select>
      </el-form-item>
      <el-form-item label="截图">
        <el-select v-model="taskForm.captureScreenshots" style="width:100%">
          <el-option label="使用项目默认" value="" />
          <el-option label="开启" value="true" />
          <el-option label="关闭" value="false" />
        </el-select>
      </el-form-item>
      <el-form-item label="参数 JSON" :error="formErrors.taskParameters">
        <el-input v-model="taskForm.parameters" type="textarea" :rows="3" @input="delete formErrors.taskParameters" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="showTaskDialog = false">取消</el-button>
      <el-button type="primary" @click="saveTask">创建</el-button>
    </template>
  </el-dialog>
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

function openReport(): void {
  if (selectedTask.value) {
    window.open(reportUrl(selectedTask.value.taskId), "_blank");
  }
}
</script>

<style scoped>
.card-header { display: flex; align-items: center; justify-content: space-between; }
.filter-bar { display: flex; gap: 12px; margin-bottom: 16px; }
.report-bar { display: flex; gap: 8px; margin-bottom: 12px; }
.empty { padding: 40px; text-align: center; color: #909399; }
</style>
