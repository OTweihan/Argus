<template>
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
import SidebarMenu from "./components/layout/SidebarMenu.vue";
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
