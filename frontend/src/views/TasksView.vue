<template>
  <div class="tasks-wrapper">
    <template v-if="view === 'task-detail'">
      <div class="report-bar">
        <el-button @click="goBackToTasks">返回任务列表</el-button>
        <template v-if="selectedTask?.reportPath">
          <el-button @click="openHtmlReport">查看 HTML 报告</el-button>
          <el-button @click="downloadHtmlReport">下载 HTML 报告</el-button>
          <el-button @click="downloadJsonReport">下载 JSON 报告</el-button>
        </template>
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
      <el-card class="tasks-card">
        <template #header>
          <div class="card-header">
            <span>任务列表</span>
            <el-button type="primary" @click="openNewTaskDialog">新增任务</el-button>
          </div>
        </template>
        <div class="filter-bar">
          <el-input v-model="taskSearchQuery" placeholder="搜索目标、任务 ID、URL" clearable class="search-input">
            <template #prefix>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
                   stroke-linejoin="round" class="search-icon">
                <circle cx="11" cy="11" r="8"/>
                <path d="m21 21-4.35-4.35"/>
              </svg>
            </template>
          </el-input>
          <el-select v-model="taskStatusFilter" placeholder="全部状态" clearable style="width:140px">
            <el-option v-for="status in taskStatuses" :key="status" :label="status" :value="status" />
          </el-select>
          <el-select v-model="taskProjectFilter" placeholder="全部项目" clearable style="width:160px">
            <el-option v-for="project in projects" :key="project.projectId" :label="project.name" :value="project.projectId" />
          </el-select>
        </div>
        <div class="table-wrap" v-loading="taskLoading">
          <TaskTable
            :tasks="allTasks"
            :projects="projects"
            height="100%"
            @select="selectTask"
            @start="startTask"
          />
        </div>
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[10, 20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            background
            @current-change="onPageChange"
            @size-change="onPageSizeChange"
          />
        </div>
      </el-card>
    </template>
  </div>

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
import TaskTable from "../components/task/TaskTable.vue";
import ReportView from "./ReportView.vue";
import { reportUrl } from "../api";
import { useConsoleApp } from "../composables/useConsoleApp";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const {
  view, projects, allTasks, taskStatusFilter, taskProjectFilter,
  taskSearchQuery, taskStatuses, selectedTask, reportData, reportLoading, taskForm,
  showTaskDialog, formErrors, error, enabledModels,
  page, pageSize, total, taskLoading,
  selectTask, startTask, goBackToTasks, saveTask, openNewTaskDialog,
  onPageChange, onPageSizeChange,
} = props.app;

function openHtmlReport(): void {
  if (selectedTask.value) {
    window.open(reportUrl(selectedTask.value.taskId), "_blank");
  }
}

function downloadHtmlReport(): void {
  if (selectedTask.value) {
    window.open(reportUrl(selectedTask.value.taskId, false, true), "_blank");
  }
}

function downloadJsonReport(): void {
  if (selectedTask.value) {
    window.open(reportUrl(selectedTask.value.taskId, true, true), "_blank");
  }
}
</script>

<style scoped>
.tasks-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tasks-card {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

:deep(.tasks-card .el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 0 20px 20px;
}

.table-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  padding: 12px 0 0;
  flex-shrink: 0;
}

.card-header { display: flex; align-items: center; justify-content: space-between; }
.filter-bar { display: flex; gap: 12px; padding: 16px 0; flex-shrink: 0; }
.search-input { max-width: 320px; }
.search-icon { width: 16px; height: 16px; color: #909399; }
.report-bar { display: flex; gap: 8px; margin-bottom: 12px; flex-shrink: 0; }
.empty { padding: 40px; text-align: center; color: #909399; }
</style>
