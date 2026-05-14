<template>
  <el-aside width="220px" class="sidebar">
    <div class="brand">
      <span class="brand-mark" aria-hidden="true">A</span>
      <span class="brand-name">Argus</span>
    </div>
    <el-menu :default-active="view" class="nav-menu" @select="onSelect">
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
const emit = defineEmits<{ changeView: [index: ViewKey] }>();

// el-menu @select 事件签名固定为 (index: string)，但模板里 4 个 menu-item
// 的 index 都硬编码为 ViewKey 的成员，运行时不会出现非 ViewKey 字符串，
// 这里 cast 即可（vue-tsc 在 inline `$emit('changeView', $event)` 形式下
// 无法做这层窄化推断，必须拆成 setup 函数）。
function onSelect(index: string): void {
    emit("changeView", index as ViewKey);
}
</script>

<style>
.sidebar {
  height: 100vh;
  background: rgba(255, 255, 255, 0.62);
  border-right: 1px solid var(--line-soft);
  display: flex;
  flex-direction: column;
  padding-top: 0;
  backdrop-filter: blur(var(--blur-strong));
  -webkit-backdrop-filter: blur(var(--blur-strong));
  position: relative;
  z-index: 6;
}

.sidebar::after {
  content: "";
  position: absolute;
  top: 0;
  bottom: 0;
  right: 0;
  width: 1px;
  background: linear-gradient(180deg, transparent 0%, var(--line-soft) 16%, var(--line-soft) 84%, transparent 100%);
  pointer-events: none;
}

.brand {
  margin: 0;
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid var(--line-soft);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.6) 0%, transparent 100%);
}

.brand-mark {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  background-image: var(--brand-gradient);
  color: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
  box-shadow: 0 6px 14px rgba(99, 102, 241, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.4);
}

.brand-name {
  font-size: 22px;
  font-weight: 720;
  letter-spacing: -0.01em;
  color: var(--text-strong);
}

.nav-menu {
  border-right: none !important;
  background: transparent !important;
  flex: 1;
  padding: 10px 0;
}

.nav-menu .el-menu-item {
  position: relative;
  margin: 3px 12px;
  border-radius: var(--radius-sm);
  height: 42px;
  line-height: 42px;
  font-size: 14px;
  color: var(--text-muted);
  transition: background var(--transition-fast), color var(--transition-fast), transform var(--transition-fast);
}

.nav-menu .el-menu-item svg {
  width: 18px;
  height: 18px;
  margin-right: 10px;
  opacity: 0.6;
  transition: opacity var(--transition-fast), color var(--transition-fast);
}

.nav-menu .el-menu-item:hover {
  background: var(--brand-50);
  color: var(--brand-700);
  transform: translateX(2px);
}

.nav-menu .el-menu-item:hover svg {
  opacity: 0.95;
  color: var(--brand-600);
}

.nav-menu .el-menu-item.is-active {
  background: var(--brand-50) !important;
  color: var(--brand-700) !important;
  font-weight: 600;
  box-shadow: inset 0 0 0 1px rgba(99, 102, 241, 0.10);
}

.nav-menu .el-menu-item.is-active::before {
  content: "";
  position: absolute;
  left: -12px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 22px;
  border-radius: 0 3px 3px 0;
  background-image: var(--brand-gradient);
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.45);
}

.nav-menu .el-menu-item.is-active svg {
  opacity: 1;
  color: var(--brand-600);
}
</style>
