<template>
  <div class="metrics">
    <div class="r-metric metric-accent-info">
      <div class="metric-icon mi-info">
        <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
          <circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4" />
          <path d="M10 7v5.5M10 5v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
      </div>
      <div class="metric-body">
        <span class="metric-label">任务状态</span>
        <strong class="metric-value">{{ statusLabel }}</strong>
      </div>
    </div>
    <div class="r-metric metric-accent-primary">
      <div class="metric-icon mi-primary">
        <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
          <path d="M4 4h12v12H4z" stroke="currentColor" stroke-width="1.4" />
          <path d="M8 10l1.5 1.5L12 8.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
      </div>
      <div class="metric-body">
        <span class="metric-label">展示步骤</span>
        <strong class="metric-value">{{ stepCount }}</strong>
      </div>
    </div>
    <div :class="['r-metric', findingCount === 0 ? 'metric-accent-success' : 'metric-accent-danger']">
      <div :class="['metric-icon', findingCount === 0 ? 'mi-success' : 'mi-danger']">
        <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
          <circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4" />
          <path v-if="findingCount === 0" d="M7 10l2 2 4-4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          <path v-else d="M10 7v4M10 13v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
      </div>
      <div class="metric-body">
        <span class="metric-label">问题数量</span>
        <strong class="metric-value">{{ findingCount }}</strong>
      </div>
    </div>
    <div class="r-metric metric-accent-warning">
      <div class="metric-icon mi-warning">
        <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
          <path d="M10 3L3 17h14L10 3z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" />
          <path d="M10 8v4M10 14v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
      </div>
      <div class="metric-body">
        <span class="metric-label">失败步骤</span>
        <strong class="metric-value">{{ failedCount }}</strong>
      </div>
    </div>
    <div class="r-metric metric-accent-info">
      <div class="metric-icon mi-info">
        <svg viewBox="0 0 20 20" fill="none" width="18" height="18">
          <path d="M2 10h4l2-5 4 10 2-5h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
      </div>
      <div class="metric-body">
        <span class="metric-label">最大步数</span>
        <strong class="metric-value">{{ maxSteps }}</strong>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  statusLabel: string;
  stepCount: number;
  findingCount: number;
  failedCount: number;
  maxSteps: number;
}>();
</script>

<style scoped>
.metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
  margin-top: -10px;
}

.r-metric {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 14px;
  border: 1px solid #e4e7ec;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.78);
  padding: 20px;
  box-shadow: 0 10px 32px rgba(15, 23, 42, 0.05);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  transition: box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1), transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.r-metric::after {
  content: "";
  position: absolute;
  right: -28px;
  bottom: -28px;
  width: 96px;
  height: 96px;
  border-radius: 999px;
  filter: blur(2px);
  opacity: 0.85;
  pointer-events: none;
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.r-metric:hover {
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.06);
  transform: translateY(-2px);
}

.r-metric:hover::after {
  transform: scale(1.08);
}

.metric-accent-primary::after { background: #eef2ff; }
.metric-accent-success::after { background: #ecfdf3; }
.metric-accent-danger::after { background: #fff1f3; }
.metric-accent-warning::after { background: #fffaeb; }
.metric-accent-info::after { background: #eff8ff; }

.metric-icon {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  flex-shrink: 0;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

.mi-primary { background: #eef2ff; color: #4f46e5; }
.mi-success { background: #ecfdf3; color: #15803d; }
.mi-danger { background: #fff1f3; color: #b42318; }
.mi-warning { background: #fffaeb; color: #b54708; }
.mi-info { background: #eff8ff; color: #175cd3; }

.metric-body {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 6px;
  min-width: 0;
}

.metric-label {
  font-size: 12px;
  color: #667085;
  font-weight: 600;
  white-space: nowrap;
}

.metric-value {
  font-size: 26px;
  font-weight: 720;
  color: #172033;
  letter-spacing: -0.04em;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
