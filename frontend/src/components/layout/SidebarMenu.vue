<template>
  <el-aside width="220px" class="sidebar">
    <h1 class="brand">Argus</h1>
    <el-menu :default-active="view" class="nav-menu" @select="$emit('changeView', $event)">
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
</template>

<script setup lang="ts">
import type {ViewKey} from "../../composables/useConsoleApp";

defineProps<{ view: ViewKey }>();
defineEmits<{ changeView: [index: ViewKey] }>();
</script>

<style>
.sidebar {
  height: 100vh;
  background: linear-gradient(180deg, #fafbfc 0%, #ffffff 100%);
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  padding-top: 0;
}

.brand {
  margin: 0;
  padding: 22px 18px;
  font-size: 30px;
  font-weight: 760;
  letter-spacing: -0.3px;
  color: #11181c;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.nav-menu {
  border-right: none !important;
  flex: 1;
  padding: 8px 0;
}

.nav-menu .el-menu-item {
  margin: 2px 8px;
  border-radius: 8px;
  height: 42px;
  line-height: 42px;
  font-size: 14px;
  transition: all 0.15s ease;
}

.nav-menu .el-menu-item svg {
  width: 18px;
  height: 18px;
  margin-right: 8px;
  opacity: 0.55;
  transition: opacity 0.15s ease;
}

.nav-menu .el-menu-item:hover {
  background: #f3f4f6;
}

.nav-menu .el-menu-item.is-active {
  background: var(--brand-accent-light) !important;
  color: var(--brand-accent) !important;
  font-weight: 600;
}

.nav-menu .el-menu-item.is-active svg {
  opacity: 1;
  color: var(--brand-accent);
}
</style>
