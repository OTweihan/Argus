<template>
  <div class="dashboard-container">
    <section class="dashboard-intro">
      <div>
        <p class="intro-kicker">WORKSPACE OVERVIEW</p>
        <h2>质量工作台</h2>
        <p>集中查看项目规模、任务进度与最近执行结果。</p>
      </div>
      <div class="intro-orbit" aria-hidden="true">
        <span />
      </div>
    </section>
    <el-row :gutter="20">
      <!-- 项目卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <DashboardMetricCard kind="projects" :value="projects.length" label="项目总数">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
          </svg>
        </DashboardMetricCard>
      </el-col>

      <!-- 任务卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <DashboardMetricCard kind="tasks" :value="tasksTotal" label="全部任务">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M9 11l3 3L22 4" />
            <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" />
          </svg>
        </DashboardMetricCard>
      </el-col>

      <!-- 运行中卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <DashboardMetricCard kind="running" :value="runningCount" label="运行中">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        </DashboardMetricCard>
      </el-col>

      <!-- 问题卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <DashboardMetricCard kind="findings" :value="findingCount" label="发现问题">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path
              d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
            />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
        </DashboardMetricCard>
      </el-col>
    </el-row>

    <!-- 最近任务列表 -->
    <el-card class="recent-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="header-title">最近任务</span>
        </div>
      </template>
      <div v-loading="statsLoading" class="table-wrap">
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
      </div>
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
import TaskTable from "../components/task/TaskTable.vue";
import TaskDetailDialog from "../components/task/TaskDetailDialog.vue";
import DashboardMetricCard from "../components/dashboard/DashboardMetricCard.vue";
import { injectConsoleApp } from "../composables/useConsoleApp";
import { useTaskViewActions } from "../composables/useTaskViewActions";

const {
  projects,
  allTasks,
  tasksTotal,
  recentTasks,
  runningCount,
  findingCount,
  enabledModels,
  error,
  selectedTask,
  selectTask,
  statsLoading,
} = injectConsoleApp();

const { detailVisible, detailLoading, detailTask, showTaskDetail } = useTaskViewActions({
  allTasks,
  selectedTask,
  error,
});

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

.dashboard-intro {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 104px;
  margin-bottom: 16px;
  padding: 20px 24px;
  overflow: hidden;
  border: 1px solid rgba(10, 186, 181, 0.18);
  border-radius: var(--radius-md);
  background:
    radial-gradient(circle at 88% 32%, rgba(10, 186, 181, 0.16), transparent 32%),
    var(--surface-glass-strong);
  box-shadow: var(--shadow-panel);
  backdrop-filter: blur(var(--blur-soft));
}

.intro-kicker {
  margin: 0 0 5px;
  color: var(--brand-700);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.16em;
}

.dashboard-intro h2 {
  margin: 0;
  color: var(--text-strong);
  font-size: 23px;
  letter-spacing: -0.02em;
}

.dashboard-intro p:last-child {
  margin: 6px 0 0;
  color: var(--text-faint);
  font-size: 13px;
}

.intro-orbit {
  position: relative;
  display: grid;
  width: 58px;
  height: 58px;
  place-items: center;
  border: 1px solid rgba(10, 186, 181, 0.2);
  border-radius: 18px;
  background: var(--brand-gradient-soft);
  box-shadow: var(--shadow-xs);
}

.intro-orbit::before,
.intro-orbit::after {
  content: "";
  position: absolute;
  border: 1px solid rgba(8, 123, 120, 0.34);
  border-radius: 50%;
}

.intro-orbit::before {
  width: 34px;
  height: 16px;
  transform: rotate(28deg);
}

.intro-orbit::after {
  width: 16px;
  height: 34px;
  transform: rotate(28deg);
}

.intro-orbit span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--brand-700);
  box-shadow: 0 0 0 5px rgba(10, 186, 181, 0.14);
}

.mb-4 {
  margin-bottom: 16px;
  flex-shrink: 0;
}

/* 最近任务卡片 */
.recent-card {
  margin-top: 4px;
  /* 与其他页面卡片统一圆角（全局 .el-card 已统一为 --radius-md） */
  border-radius: var(--radius-md);
  border: 1px solid var(--line-soft);
  background: var(--surface-glass-strong);
  box-shadow: var(--shadow-panel);
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
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 18px;
  background-image: var(--brand-gradient-strong);
  border-radius: 2px;
  box-shadow: 0 4px 10px rgba(10, 186, 181, 0.3);
}

.table-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
</style>
