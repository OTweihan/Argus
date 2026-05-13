<template>
  <el-config-provider :locale="zhCn">
    <el-container class="shell">
      <SidebarMenu :view="view" @changeView="changeView"/>

      <el-container class="main-area">
        <el-header class="topbar">
          <h1>{{ viewTitle }}</h1>
          <div class="status">
            <span class="dot" :class="eventStatus"></span>
            <span>事件流：{{ eventStatusText }}</span>
            <el-button @click="loadAll">刷新</el-button>
          </div>
        </el-header>

        <el-main class="content-area">
          <el-alert v-if="loading" type="info" :closable="false" show-icon title="正在加载数据" class="banner"/>

          <Suspense>
            <template #default>
              <component :is="currentView" :app="consoleApp"/>
            </template>
            <template #fallback>
              <div class="view-loading">正在加载视图…</div>
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
          <el-button type="primary" @click="closeDialog">确定</el-button>
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
.view-loading {
  padding: 40px;
  text-align: center;
  color: #909399;
}
</style>
