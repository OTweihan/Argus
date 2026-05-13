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
      <template v-else>
        <el-tabs v-model="selectedTaskTab" type="border-card" class="detail-tabs">
          <el-tab-pane label="报告" name="report">
            <ReportView
                :key="selectedTask.taskId"
                :report="reportData"
                :loading="reportLoading"
                :task-id="selectedTask.taskId"
            />
          </el-tab-pane>
          <el-tab-pane label="执行时间线" name="timeline">
            <TaskTimeline :key="selectedTask.taskId" :task-id="selectedTask.taskId" :on-task-event="onTaskEvent" />
          </el-tab-pane>
          <el-tab-pane label="LLM 调试" name="llm-debug">
            <LLMDebugTab :key="selectedTask.taskId" :task-id="selectedTask.taskId" />
          </el-tab-pane>
        </el-tabs>
      </template>
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
            <el-option v-for="status in taskStatuses" :key="status" :label="status" :value="status"/>
          </el-select>
          <el-select v-model="taskProjectFilter" placeholder="全部项目" clearable style="width:160px">
            <el-option v-for="project in projects" :key="project.projectId" :label="project.name"
                       :value="project.projectId"/>
          </el-select>
        </div>
        <div class="table-wrap" v-loading="taskLoading">
          <TaskTable
              :tasks="allTasks"
              :projects="projects"
              height="100%"
              @select="showTaskDetail"
              @report="showTaskReport"
              @edit="editTask"
              @start="startTask"
              @restart="retryTask"
              @delete="deleteTask"
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

  <TaskFormDialog
      :visible="showTaskDialog"
      :form="taskForm"
      :editing="Boolean(taskForm.editingId)"
      :form-errors="formErrors"
      :projects="projects"
      :enabled-models="enabledModels"
      @save="saveTask"
      @close="showTaskDialog = false"
      @add-param="addParam()"
      @remove-param="removeParam($event)"
  />

  <TaskDetailDialog
      :visible="detailVisible"
      :task="detailTask"
      :loading="detailLoading"
      :projects="projects"
      :enabled-models="enabledModels"
      @close="detailVisible = false"
  />

</template>

<script setup lang="ts">
import {ref} from "vue";
import TaskTable from "../components/task/TaskTable.vue";
import TaskFormDialog from "../components/task/TaskFormDialog.vue";
import TaskDetailDialog from "../components/task/TaskDetailDialog.vue";
import LLMDebugTab from "../components/task/LLMDebugTab.vue";
import TaskTimeline from "../components/task/TaskTimeline.vue";
import ReportView from "./ReportView.vue";
import {getTask, reportUrl} from "../api";
import {useConsoleApp} from "../composables/useConsoleApp";
import type {Task} from "../types";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const {
  view, projects, allTasks, taskStatusFilter, taskProjectFilter,
  taskSearchQuery, taskStatuses, selectedTask, selectedTaskTab, reportData, reportLoading, taskForm,
  showTaskDialog, formErrors, error, enabledModels,
  page, pageSize, total, taskLoading,
  startTask, retryTask, deleteTask, goBackToTasks, saveTask, openNewTaskDialog, openEditTaskDialog,
  addParam, removeParam, onPageChange, onPageSizeChange, onTaskEvent, selectTask,
} = props.app;

const detailVisible = ref(false);
const detailLoading = ref(false);
const detailTask = ref<Task | null>(null);

async function showTaskDetail(taskId: string): Promise<void> {
  detailVisible.value = true;
  detailLoading.value = true;
  detailTask.value = null;
  try {
    detailTask.value = await getTask(taskId);
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "获取任务详情失败";
    detailVisible.value = false;
  } finally {
    detailLoading.value = false;
  }
}

async function showTaskReport(taskId: string): Promise<void> {
  await selectTask(taskId, "report");
}

function editTask(task: Task): void {
  openEditTaskDialog(task);
}

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

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.filter-bar {
  display: flex;
  gap: 12px;
  padding: 16px 0;
  flex-shrink: 0;
}

.search-input {
  max-width: 320px;
}

.search-icon {
  width: 16px;
  height: 16px;
  color: #909399;
}

.report-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.empty {
  padding: 40px;
  text-align: center;
  color: #909399;
}

.detail-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.detail-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.detail-tabs :deep(.el-tab-pane) {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

</style>
