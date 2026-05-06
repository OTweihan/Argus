<template>
  <div class="shell">
    <aside class="sidebar">
      <h1 class="brand">Argus</h1>
      <nav class="nav">
        <button :class="{ active: view === 'dashboard' }" @click="changeView('dashboard')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1"/>
            <rect x="14" y="3" width="7" height="7" rx="1"/>
            <rect x="3" y="14" width="7" height="7" rx="1"/>
            <rect x="14" y="14" width="7" height="7" rx="1"/>
          </svg>
          仪表盘
        </button>
        <button :class="{ active: view === 'projects' }" @click="changeView('projects')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round">
            <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>
          </svg>
          项目
        </button>
        <button :class="{ active: view === 'tasks' }" @click="changeView('tasks')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round">
            <path d="M9 11l3 3L22 4"/>
            <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>
          </svg>
          任务
        </button>
        <button :class="{ active: view === 'models' }" @click="changeView('models')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z"/>
            <path d="M2 17l10 5 10-5"/>
            <path d="M2 12l10 5 10-5"/>
          </svg>
          模型
        </button>
      </nav>
    </aside>

    <main class="main">
      <div class="topbar">
        <h1>{{ viewTitle }}</h1>
        <div class="status">
          <span class="dot" :class="eventStatus"></span>
          <span>事件流：{{ eventStatusText }}</span>
          <button type="button" @click="loadAll">刷新</button>
        </div>
      </div>

      <div v-if="loading" class="banner">正在加载数据</div>
      <div v-if="message" class="banner">{{ message }}</div>
      <div v-if="error" class="banner error dialog-error">{{ error }}</div>

      <DashboardView v-if="view === 'dashboard'" :app="consoleApp" />
      <ProjectsView v-else-if="view === 'projects'" :app="consoleApp" />
      <TasksView v-else-if="view === 'tasks'" :app="consoleApp" />
      <TasksView v-else-if="view === 'task-detail'" :app="consoleApp" />
      <ModelsView v-else :app="consoleApp" />
    </main>

    <div v-if="dialog" class="dialog-backdrop" @click.self="closeDialog">
      <div class="dialog" :class="dialog.tone" role="dialog" aria-modal="true">
        <div class="dialog-header">
          <h2>{{ dialog.title }}</h2>
          <button type="button" aria-label="关闭" @click="closeDialog">×</button>
        </div>
        <div class="dialog-body">{{ dialog.message }}</div>
        <div class="dialog-actions">
          <button class="primary" type="button" @click="closeDialog">确定</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import DashboardView from "./views/DashboardView.vue";
import ProjectsView from "./views/ProjectsView.vue";
import TasksView from "./views/TasksView.vue";
import ModelsView from "./views/ModelsView.vue";
import { useConsoleApp } from "./composables/useConsoleApp";

const consoleApp = useConsoleApp();

const {
  view,
  viewTitle,
  eventStatus,
  eventStatusText,
  loading,
  message,
  error,
  dialog,
  closeDialog,
  loadAll,
  changeView,
} = consoleApp;
</script>
