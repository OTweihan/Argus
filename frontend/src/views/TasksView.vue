<template>
  <div class="tasks-wrapper">
    <div v-if="view === 'task-detail'" class="task-detail-panel">
      <div class="report-bar">
        <button class="tb-btn tb-back" @click="goBackToTasks">
          <svg viewBox="0 0 16 16" fill="none" width="20" height="20">
            <path
              d="M10 4L6 8l4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          返回任务列表
        </button>
        <template v-if="selectedTask?.reportPath">
          <div class="tb-divider" />
          <button class="tb-btn tb-action" @click="openHtmlReport">
            <svg viewBox="0 0 16 16" fill="none" width="20" height="20">
              <path
                d="M2 4l6 4-6 4M8 12h6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            查看 HTML 报告
          </button>
          <button class="tb-btn tb-action" @click="downloadHtmlReport">
            <svg viewBox="0 0 16 16" fill="none" width="20" height="20">
              <path
                d="M8 2v8M4 6l4 4 4-4M2 12v2h12v-2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            下载 HTML 报告
          </button>
          <button class="tb-btn tb-action" @click="downloadJsonReport">
            <svg viewBox="0 0 16 16" fill="none" width="20" height="20">
              <path
                d="M5 7l-3 3 3 3M11 7l3 3-3 3M8.5 4l-1 8" stroke="currentColor" stroke-width="1.4"
                stroke-linecap="round"
              />
            </svg>
            下载 JSON 报告
          </button>
        </template>
      </div>
      <div v-if="!selectedTask" class="empty">
        未选择任务
      </div>
      <template v-else>
        <el-tabs v-model="selectedTaskTab" type="border-card" class="detail-tabs">
          <el-tab-pane lazy label="报告" name="report">
            <ReportView
              :key="selectedTask.taskId"
              :report="reportData"
              :loading="reportLoading"
              :task-id="selectedTask.taskId"
            />
          </el-tab-pane>
          <el-tab-pane lazy label="执行时间线" name="timeline">
            <TaskTimeline :key="selectedTask.taskId" :task-id="selectedTask.taskId" :on-task-event="onTaskEvent" />
          </el-tab-pane>
          <el-tab-pane lazy label="LLM 调试" name="llm-debug">
            <LLMDebugTab :key="selectedTask.taskId" :task-id="selectedTask.taskId" />
          </el-tab-pane>
        </el-tabs>
      </template>
    </div>
    <div v-show="view !== 'task-detail'" class="tasks-list-panel">
      <el-card class="tasks-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">任务列表</span>
            <el-button type="primary" @click="openNewTaskDialog">
              新增任务
            </el-button>
          </div>
        </template>
        <div class="filter-bar">
          <el-input v-model="taskSearchQuery" placeholder="搜索目标、任务 ID、URL" clearable class="search-input">
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
          <el-select v-model="taskStatusFilter" placeholder="全部状态" clearable style="width:140px">
            <el-option v-for="status in taskStatuses" :key="status" :label="status" :value="status" />
          </el-select>
          <el-select v-model="taskProjectFilter" placeholder="全部项目" clearable style="width:160px">
            <el-option
              v-for="project in projects" :key="project.projectId" :label="project.name"
              :value="project.projectId"
            />
          </el-select>
        </div>
        <div v-loading="taskLoading" class="table-wrap">
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
import {defineAsyncComponent} from "vue";
import TaskTable from "../components/task/TaskTable.vue";
import TaskFormDialog from "../components/task/TaskFormDialog.vue";
import TaskDetailDialog from "../components/task/TaskDetailDialog.vue";
import {injectConsoleApp} from "../composables/useConsoleApp";
import {useTaskViewActions} from "../composables/useTaskViewActions";
import type {Task} from "../types";
// 任务详情页三个大体积 Tab 组件按需加载，避免拖慢任务列表首屏
const ReportView = defineAsyncComponent(() => import("./ReportView.vue"));
const TaskTimeline = defineAsyncComponent(() => import("../components/task/TaskTimeline.vue"));
const LLMDebugTab = defineAsyncComponent(() => import("../components/task/LLMDebugTab.vue"));

const {
  view, projects, allTasks, taskStatusFilter, taskProjectFilter,
  taskSearchQuery, taskStatuses, selectedTask, selectedTaskTab, reportData, reportLoading, taskForm,
  showTaskDialog, formErrors, error, enabledModels,
  page, pageSize, total, taskLoading,
  startTask, retryTask, deleteTask, goBackToTasks, saveTask, openNewTaskDialog, openEditTaskDialog,
  addParam, removeParam, onPageChange, onPageSizeChange, onTaskEvent, selectTask,
} = injectConsoleApp();

const {
  detailVisible, detailLoading, detailTask, showTaskDetail,
  openHtmlReport, downloadHtmlReport, downloadJsonReport,
} = useTaskViewActions({allTasks, selectedTask, error});

async function showTaskReport(taskId: string): Promise<void> {
  await selectTask(taskId, "report");
}

function editTask(task: Task): void {
  openEditTaskDialog(task);
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
  padding: 0 22px 22px;
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
  padding: 14px 0 0;
  flex-shrink: 0;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.filter-bar {
  display: flex;
  gap: 12px;
  padding: 18px 0 14px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--line-soft);
  margin-bottom: 4px;
}

.search-input {
  max-width: 320px;
}

.search-icon {
  width: 16px;
  height: 16px;
  color: var(--text-placeholder, #9ca3af);
}

/* 任务详情顶部工具条：玻璃面板，与 tabs 头条粘合形成统一固定头部 */
.report-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 0;
  flex-shrink: 0;
  flex-wrap: wrap;
  padding: 10px 14px;
  background: var(--surface-glass-strong);
  border: 1px solid var(--line-soft);
  border-bottom: 0;
  border-top-left-radius: var(--radius-md);
  border-top-right-radius: var(--radius-md);
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
  box-shadow: var(--shadow-xs);
  backdrop-filter: blur(var(--blur-soft));
  -webkit-backdrop-filter: blur(var(--blur-soft));
  position: relative;
  z-index: 3;
}

.tb-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 540;
  font-family: inherit;
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
  line-height: 1;
}

.tb-back {
  background: var(--surface-soft);
  color: var(--text-muted);
  border-color: var(--line-soft);
}

.tb-back:hover {
  background: rgba(241, 245, 249, 0.9);
  color: var(--text-strong);
  border-color: var(--line-strong);
  transform: translateX(-1px);
  box-shadow: var(--shadow-xs);
}

.tb-action {
  background: var(--brand-50);
  color: var(--brand-600);
  border-color: var(--brand-100);
}

.tb-action:hover {
  background: var(--brand-100);
  color: var(--brand-700);
  border-color: var(--brand-200);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.18);
  transform: translateY(-1px);
}

.tb-divider {
  width: 1px;
  height: 20px;
  background: var(--line-soft);
  flex-shrink: 0;
  margin: 0 4px;
}

.empty {
  padding: 48px;
  text-align: center;
  color: var(--text-faint);
}

.detail-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  /* 与上方 report-bar 视觉粘合，形成连续顶部固定头部 */
  border-top-left-radius: 0 !important;
  border-top-right-radius: 0 !important;
}

/* tab 头条：固定不滚动 + 下沉阴影强化「悬浮在内容之上」感 */
.detail-tabs :deep(.el-tabs__header) {
  flex-shrink: 0;
  position: relative;
  z-index: 2;
  margin: 0;
  box-shadow: 0 6px 14px -10px rgba(15, 23, 42, 0.18);
}

.detail-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
  z-index: 1;
}

.detail-tabs :deep(.el-tab-pane) {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

</style>
