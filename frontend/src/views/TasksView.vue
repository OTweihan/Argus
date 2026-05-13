<template>
  <div class="tasks-wrapper">
    <div v-if="view === 'task-detail'" class="task-detail-panel">
      <div class="report-bar">
        <button class="tb-btn tb-back" @click="goBackToTasks">
          <svg viewBox="0 0 16 16" fill="none" width="20" height="20"><path d="M10 4L6 8l4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          返回任务列表
        </button>
        <template v-if="selectedTask?.reportPath">
          <div class="tb-divider"/>
          <button class="tb-btn tb-action" @click="openHtmlReport">
            <svg viewBox="0 0 16 16" fill="none" width="20" height="20"><path d="M2 4l6 4-6 4M8 12h6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
            查看 HTML 报告
          </button>
          <button class="tb-btn tb-action" @click="downloadHtmlReport">
            <svg viewBox="0 0 16 16" fill="none" width="20" height="20"><path d="M8 2v8M4 6l4 4 4-4M2 12v2h12v-2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
            下载 HTML 报告
          </button>
          <button class="tb-btn tb-action" @click="downloadJsonReport">
            <svg viewBox="0 0 16 16" fill="none" width="20" height="20"><path d="M5 7l-3 3 3 3M11 7l3 3-3 3M8.5 4l-1 8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
            下载 JSON 报告
          </button>
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
    </div>
    <div v-show="view !== 'task-detail'" class="tasks-list-panel">
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
    </div>
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
import {defineAsyncComponent, ref} from "vue";
import TaskTable from "../components/task/TaskTable.vue";
import TaskFormDialog from "../components/task/TaskFormDialog.vue";
import TaskDetailDialog from "../components/task/TaskDetailDialog.vue";
// 任务详情页三个大体积 Tab 组件按需加载，避免拖慢任务列表首屏
const ReportView = defineAsyncComponent(() => import("./ReportView.vue"));
const TaskTimeline = defineAsyncComponent(() => import("../components/task/TaskTimeline.vue"));
const LLMDebugTab = defineAsyncComponent(() => import("../components/task/LLMDebugTab.vue"));
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

.task-detail-panel,
.tasks-list-panel {
  flex: 1;
  min-height: 0;
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
  align-items: center;
  gap: 6px;
  margin-bottom: 16px;
  flex-shrink: 0;
  flex-wrap: wrap;
  padding: 8px 12px;
  background: #ffffff;
  border: 1px solid #e6edf0;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(24, 40, 50, 0.05);
}

.tb-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1px solid transparent;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 540;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  line-height: 1;
}

.tb-back {
  background: #f8fafc;
  color: #374e5a;
  border-color: #e6edf0;
}
.tb-back:hover {
  background: #eef4f7;
  color: #1a2a32;
  border-color: #d0dbdf;
  box-shadow: 0 1px 3px rgba(24, 40, 50, 0.06);
}

.tb-action {
  background: #f0f6ff;
  color: #2563eb;
  border-color: #dbe8fe;
}
.tb-action:hover {
  background: #dbe8fe;
  color: #1d4ed8;
  border-color: #b8d2fb;
  box-shadow: 0 1px 3px rgba(37, 99, 235, 0.1);
}

.tb-divider {
  width: 1px;
  height: 20px;
  background: #e6edf0;
  flex-shrink: 0;
  margin: 0 2px;
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
