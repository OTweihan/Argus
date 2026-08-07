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
  /* 与其他页面卡片统一圆角（全局 .el-card 已统一为 --radius-md） */
  border-radius: var(--radius-md);
  border: 1px solid var(--line-soft);
  background: var(--surface-glass-strong);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(var(--blur-soft));
  -webkit-backdrop-filter: blur(var(--blur-soft));
  transition:
    transform var(--transition-base),
    box-shadow var(--transition-base);
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

.metric-card:hover .metric-icon {
  transform: scale(1.08);
}
.metric-projects .metric-icon {
  background: linear-gradient(135deg, #ecfefd, #cffaf8);
  color: var(--brand-700);
}
.metric-tasks .metric-icon {
  background: linear-gradient(135deg, #ecfdf5, #d1fae5);
  color: #059669;
}
.metric-running .metric-icon {
  background: linear-gradient(135deg, #fffbeb, #fef3c7);
  color: #d97706;
}
.metric-findings .metric-icon {
  background: linear-gradient(135deg, #fef2f2, #fee2e2);
  color: #dc2626;
}

.metric-info {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}
.metric-value {
  font-size: 30px;
  font-weight: 720;
  color: var(--text-strong);
  line-height: 1.15;
  letter-spacing: -0.02em;
  font-family:
    "Inter",
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    Roboto,
    sans-serif;
}
.metric-label {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 540;
  color: var(--text-faint);
}
</style>
