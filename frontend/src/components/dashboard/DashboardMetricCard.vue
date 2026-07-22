<template>
  <el-card shadow="hover" class="metric-card" :class="`metric-${kind}`">
    <div class="metric-content">
      <div class="metric-icon">
        <slot />
      </div>
      <div class="metric-info">
        <div class="metric-value">
          {{ value }}
        </div>
        <div class="metric-label">
          {{ label }}
        </div>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  kind: "projects" | "tasks" | "running" | "findings";
  value: number;
  label: string;
}>();
</script>

<style scoped>
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

:deep(.el-card__body) {
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

.metric-icon :deep(svg) {
  width: 24px;
  height: 24px;
}

.metric-card:hover .metric-icon { transform: scale(1.08); }
.metric-projects .metric-icon { background: linear-gradient(135deg, #eef2ff, #e0e7ff); color: var(--brand-600); }
.metric-projects::after { background: linear-gradient(135deg, rgba(99, 102, 241, 0.18), rgba(139, 92, 246, 0.10)); }
.metric-tasks .metric-icon { background: linear-gradient(135deg, #ecfdf5, #d1fae5); color: #059669; }
.metric-tasks::after { background: linear-gradient(135deg, rgba(16, 185, 129, 0.18), rgba(5, 150, 105, 0.08)); }
.metric-running .metric-icon { background: linear-gradient(135deg, #fffbeb, #fef3c7); color: #d97706; }
.metric-running::after { background: linear-gradient(135deg, rgba(245, 158, 11, 0.20), rgba(217, 119, 6, 0.08)); }
.metric-findings .metric-icon { background: linear-gradient(135deg, #fef2f2, #fee2e2); color: #dc2626; }
.metric-findings::after { background: linear-gradient(135deg, rgba(239, 68, 68, 0.18), rgba(220, 38, 38, 0.08)); }

.metric-info { display: flex; flex-direction: column; justify-content: center; min-width: 0; }
.metric-value {
  font-size: 30px;
  font-weight: 720;
  color: var(--text-strong);
  line-height: 1.15;
  letter-spacing: -0.02em;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.metric-label { margin-top: 6px; font-size: 13px; font-weight: 540; color: var(--text-faint); }
</style>
