<template>
  <el-container class="shell">
    <el-aside width="220px" class="sidebar">
      <h1 class="brand">Argus</h1>
      <el-menu :default-active="view" class="nav-menu" @select="changeView">
        <el-menu-item index="dashboard">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1"/>
            <rect x="14" y="3" width="7" height="7" rx="1"/>
            <rect x="3" y="14" width="7" height="7" rx="1"/>
            <rect x="14" y="14" width="7" height="7" rx="1"/>
          </svg>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="projects">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round">
            <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>
          </svg>
          <span>项目</span>
        </el-menu-item>
        <el-menu-item index="tasks">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round">
            <path d="M9 11l3 3L22 4"/>
            <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>
          </svg>
          <span>任务</span>
        </el-menu-item>
        <el-menu-item index="models">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z"/>
            <path d="M2 17l10 5 10-5"/>
            <path d="M2 12l10 5 10-5"/>
          </svg>
          <span>模型</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="main-area">
      <el-header class="topbar">
        <h1>{{ viewTitle }}</h1>
        <div class="status">
          <span class="dot" :class="eventStatus"></span>
          <span>事件流：{{ eventStatusText }}</span>
          <el-button size="small" @click="loadAll">刷新</el-button>
        </div>
      </el-header>

      <el-main class="content-area">
        <el-alert v-if="loading" type="info" :closable="false" show-icon title="正在加载数据" class="banner"/>

        <DashboardView v-if="view === 'dashboard'" :app="consoleApp"/>
        <ProjectsView v-else-if="view === 'projects'" :app="consoleApp"/>
        <TasksView v-else-if="view === 'tasks'" :app="consoleApp"/>
        <TasksView v-else-if="view === 'task-detail'" :app="consoleApp"/>
        <ModelsView v-else :app="consoleApp"/>
      </el-main>
    </el-container>

    <el-dialog
        v-model="dialogVisible"
        :title="dialog?.title ?? ''"
        :width="dialog?.tone === 'error' ? '420px' : '420px'"
        :show-close="true"
        append-to-body
    >
      <span>{{ dialog?.message }}</span>
      <template #footer>
        <el-button type="primary" @click="closeDialog">确定</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import DashboardView from "./views/DashboardView.vue";
import ProjectsView from "./views/ProjectsView.vue";
import TasksView from "./views/TasksView.vue";
import ModelsView from "./views/ModelsView.vue";
import {useConsoleApp} from "./composables/useConsoleApp";

const consoleApp = useConsoleApp();

const {
  view,
  viewTitle,
  eventStatus,
  eventStatusText,
  loading,
  dialog,
  closeDialog,
  loadAll,
  changeView,
  dialogVisible,
} = consoleApp;
</script>
