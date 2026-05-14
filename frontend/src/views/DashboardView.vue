<template>
  <div class="dashboard-container">
    <el-row :gutter="20">
      <!-- 项目卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <el-card shadow="hover" class="metric-card metric-projects">
          <div class="metric-content">
            <div class="metric-icon">
              <svg
                viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
              </svg>
            </div>
            <div class="metric-info">
              <div class="metric-value">
                {{ projects.length }}
              </div>
              <div class="metric-label">
                项目总数
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 任务卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <el-card shadow="hover" class="metric-card metric-tasks">
          <div class="metric-content">
            <div class="metric-icon">
              <svg
                viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M9 11l3 3L22 4" />
                <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" />
              </svg>
            </div>
            <div class="metric-info">
              <div class="metric-value">
                {{ allTasks.length }}
              </div>
              <div class="metric-label">
                全部任务
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 运行中卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <el-card shadow="hover" class="metric-card metric-running">
          <div class="metric-content">
            <div class="metric-icon">
              <svg
                viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
                stroke-linejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
            </div>
            <div class="metric-info">
              <div class="metric-value">
                {{ runningCount }}
              </div>
              <div class="metric-label">
                运行中
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 问题卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <el-card shadow="hover" class="metric-card metric-findings">
          <div class="metric-content">
            <div class="metric-icon">
              <svg
                viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            </div>
            <div class="metric-info">
              <div class="metric-value">
                {{ findingCount }}
              </div>
              <div class="metric-label">
                发现问题
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 最近任务列表 -->
    <el-card class="recent-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="header-title">最近任务</span>
        </div>
      </template>
      <TaskTable
        :tasks="recentTasks"
        :projects="projects"
        :show-edit="false"
        :show-delete="false"
        :show-run-actions="false"
        compact-actions
        @select="showTaskDetail"
        @report="showTaskReport"
      />
    </el-card>

    <TaskDetailDialog
      :visible="detailVisible"
      :task="detailTask"
      :loading="detailLoading"
      :projects="projects"
      :enabled-models="enabledModels"
      @close="detailVisible = false"
    />
  </div>
</template>

<script setup lang="ts">
import {ref} from "vue";
import TaskTable from "../components/task/TaskTable.vue";
import TaskDetailDialog from "../components/task/TaskDetailDialog.vue";
import {getTask} from "../api";
import {useConsoleApp} from "../composables/useConsoleApp";
import type {Task} from "../types";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const {
  projects,
  allTasks,
  recentTasks,
  runningCount,
  findingCount,
  enabledModels,
  error,
  selectTask,
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
</script>

<style scoped>
.dashboard-container {
  padding: 4px 0 8px;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.mb-4 {
  margin-bottom: 16px;
  flex-shrink: 0;
}

/* 顶部数据卡片：玻璃面板 + 角落柔光 */
.metric-card {
  position: relative;
  overflow: hidden;
  border-radius: var(--radius-lg);
  border: 1px solid var(--line-soft);
  background: var(--surface-glass-strong);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(var(--blur-soft));
  -webkit-backdrop-filter: blur(var(--blur-soft));
  transition: transform var(--transition-base), box-shadow var(--transition-base);
}

.metric-card::after {
  content: "";
  position: absolute;
  right: -36px;
  bottom: -36px;
  width: 120px;
  height: 120px;
  border-radius: 999px;
  background: var(--brand-gradient-soft);
  filter: blur(2px);
  pointer-events: none;
  transition: transform var(--transition-slow), opacity var(--transition-slow);
  opacity: 0.85;
}

:deep(.metric-card .el-card__body) {
  position: relative;
  z-index: 1;
  padding: 22px;
}

.metric-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-md);
}

.metric-card:hover::after {
  transform: scale(1.08);
  opacity: 1;
}

.metric-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.metric-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: var(--radius-md);
  flex-shrink: 0;
  transition: transform var(--transition-base);
}

.metric-icon svg {
  width: 24px;
  height: 24px;
}

.metric-card:hover .metric-icon {
  transform: scale(1.08);
}

/* 各卡片主题色（与全局状态色协调） */
.metric-projects .metric-icon {
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  color: var(--brand-600);
}

.metric-projects::after {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.18), rgba(139, 92, 246, 0.10));
}

.metric-tasks .metric-icon {
  background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
  color: #059669;
}

.metric-tasks::after {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.18), rgba(5, 150, 105, 0.08));
}

.metric-running .metric-icon {
  background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
  color: #d97706;
}

.metric-running::after {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.20), rgba(217, 119, 6, 0.08));
}

.metric-findings .metric-icon {
  background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
  color: #dc2626;
}

.metric-findings::after {
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.18), rgba(220, 38, 38, 0.08));
}

.metric-info {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}

.metric-value {
  font-size: 30px;
  font-weight: 720;
  color: var(--text-strong);
  line-height: 1.15;
  letter-spacing: -0.02em;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

.metric-label {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 540;
  color: var(--text-faint);
}

/* 最近任务卡片 */
.recent-card {
  margin-top: 4px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--line-soft);
  background: var(--surface-glass-strong);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(var(--blur-soft));
  -webkit-backdrop-filter: blur(var(--blur-soft));
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

:deep(.recent-card .el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 0 22px 22px;
}

.card-header {
  display: flex;
  align-items: center;
}

.header-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-strong);
  position: relative;
  padding-left: 14px;
}

.header-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 18px;
  background-image: var(--brand-gradient);
  border-radius: 2px;
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.35);
}
</style>
