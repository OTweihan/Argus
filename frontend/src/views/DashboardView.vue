<template>
  <div class="dashboard-container">
    <el-row :gutter="20">
      <!-- 项目卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <el-card shadow="hover" class="metric-card metric-projects">
          <div class="metric-content">
            <div class="metric-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>
              </svg>
            </div>
            <div class="metric-info">
              <div class="metric-value">{{ projects.length }}</div>
              <div class="metric-label">项目总数</div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 任务卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <el-card shadow="hover" class="metric-card metric-tasks">
          <div class="metric-content">
            <div class="metric-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 11l3 3L22 4"/>
                <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>
              </svg>
            </div>
            <div class="metric-info">
              <div class="metric-value">{{ allTasks.length }}</div>
              <div class="metric-label">全部任务</div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 运行中卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <el-card shadow="hover" class="metric-card metric-running">
          <div class="metric-content">
            <div class="metric-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/>
                <polyline points="12 6 12 12 16 14"/>
              </svg>
            </div>
            <div class="metric-info">
              <div class="metric-value">{{ runningCount }}</div>
              <div class="metric-label">运行中</div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 问题卡片 -->
      <el-col :xs="24" :sm="12" :lg="6" class="mb-4">
        <el-card shadow="hover" class="metric-card metric-findings">
          <div class="metric-content">
            <div class="metric-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
                <line x1="12" y1="9" x2="12" y2="13"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
            </div>
            <div class="metric-info">
              <div class="metric-value">{{ findingCount }}</div>
              <div class="metric-label">发现问题</div>
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
        @select="selectTask"
        @start="startTask"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import TaskTable from "../components/TaskTable.vue";
import { useConsoleApp } from "../composables/useConsoleApp";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const { projects, allTasks, recentTasks, runningCount, findingCount, selectTask, startTask } = props.app;
</script>

<style scoped>
/* 容器及基础间距 */
.dashboard-container {
  padding: 8px 0;
}
.mb-4 {
  margin-bottom: 16px;
}

/* 顶部数据卡片通用样式 */
.metric-card {
  border: none;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

/* 覆盖 el-card 的默认 padding，使其更紧凑匀称 */
:deep(.metric-card .el-card__body) {
  padding: 20px;
}

.metric-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 20px -4px rgba(0, 0, 0, 0.08);
}

.metric-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

/* 图标容器 */
.metric-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: 14px;
  flex-shrink: 0;
  transition: transform 0.3s ease;
}

.metric-icon svg {
  width: 24px;
  height: 24px;
}

.metric-card:hover .metric-icon {
  transform: scale(1.08);
}

/* 各卡片主题色配置 (使用现代化的渐变与色彩) */
.metric-projects .metric-icon {
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  color: #4f46e5;
}
.metric-tasks .metric-icon {
  background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
  color: #10b981;
}
.metric-running .metric-icon {
  background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
  color: #f59e0b;
}
.metric-findings .metric-icon {
  background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
  color: #ef4444;
}

/* 数据展示文本 */
.metric-info {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.metric-value {
  font-size: 28px;
  font-weight: 700;
  color: #111827;
  line-height: 1.2;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

.metric-label {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 500;
  color: #6b7280;
}

/* 底部最近任务卡片 */
.recent-card {
  margin-top: 8px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
}

/* 重塑卡片头部 */
.card-header {
  display: flex;
  align-items: center;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: #111827;
  position: relative;
  padding-left: 12px;
}

/* 标题左侧小装饰条 */
.header-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 16px;
  background-color: #4f46e5;
  border-radius: 2px;
}
</style>
