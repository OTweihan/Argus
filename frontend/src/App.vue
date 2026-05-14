<template>
  <el-config-provider :locale="zhCn">
    <el-container class="shell">
      <SidebarMenu :view="view" @change-view="changeView" />

      <el-container class="main-area">
        <el-header class="topbar">
          <h1>{{ viewTitle }}</h1>
          <div class="topbar-actions">
            <div class="status">
              <span class="dot" :class="eventStatus" />
              <span>事件流：{{ eventStatusText }}</span>
            </div>
            <el-button class="refresh-btn" type="primary" plain @click="loadAll">
              <svg
                viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
                stroke-linejoin="round" width="16" height="16" class="refresh-icon"
              >
                <path d="M21 12a9 9 0 11-3.51-7.13L21 8" />
                <polyline points="21 3 21 8 16 8" />
              </svg>
              刷新
            </el-button>
          </div>
        </el-header>

        <el-main class="content-area">
          <el-alert v-if="loading" type="info" :closable="false" show-icon title="正在加载数据" class="banner" />

          <Suspense>
            <template #default>
              <component :is="currentView" :app="consoleApp" />
            </template>
            <template #fallback>
              <div class="view-loading">
                <span class="view-loading-spinner" />
                <span>正在加载视图…</span>
              </div>
            </template>
          </Suspense>
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
          <el-button type="primary" @click="closeDialog">
            确定
          </el-button>
        </template>
      </el-dialog>
    </el-container>
  </el-config-provider>
</template>

<script setup lang="ts">
import {computed, defineAsyncComponent} from "vue";
import zhCn from "element-plus/dist/locale/zh-cn.mjs";
import SidebarMenu from "./components/layout/SidebarMenu.vue";
import {useConsoleApp} from "./composables/useConsoleApp";

// 路由级懒加载：四个视图按需加载，减小首屏 JS 体积
const DashboardView = defineAsyncComponent(() => import("./views/DashboardView.vue"));
const ProjectsView = defineAsyncComponent(() => import("./views/ProjectsView.vue"));
const TasksView = defineAsyncComponent(() => import("./views/TasksView.vue"));
const ModelsView = defineAsyncComponent(() => import("./views/ModelsView.vue"));

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

const currentView = computed(() => {
  switch (view.value) {
    case "dashboard": return DashboardView;
    case "projects": return ProjectsView;
    case "tasks":
    case "task-detail": return TasksView;
    case "models": return ModelsView;
    default: return ModelsView;
  }
});
</script>

<style scoped>
.topbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.refresh-icon {
  flex-shrink: 0;
}

.view-loading {
  padding: 48px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-faint, #6b7280);
  font-size: 14px;
}

.view-loading-spinner {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 2.4px solid rgba(99, 102, 241, 0.18);
  border-top-color: var(--brand-600, #4f46e5);
  animation: view-loading-spin 0.85s linear infinite;
}

@keyframes view-loading-spin {
  to { transform: rotate(360deg); }
}
</style>
