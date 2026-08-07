<template>
  <div class="banner" :class="bannerClass">
    <div class="banner-icon">
      <svg v-if="status === 'COMPLETE'" viewBox="0 0 20 20" fill="none" width="20" height="20">
        <circle cx="10" cy="10" r="9" stroke="currentColor" stroke-width="1.4" />
        <path
          d="M6 10l3 3 5-5"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
      <svg v-else-if="status === 'DEGRADED'" viewBox="0 0 20 20" fill="none" width="20" height="20">
        <path
          d="M10 2L2 18h16L10 2z"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linejoin="round"
        />
        <line
          x1="10"
          y1="9"
          x2="10"
          y2="13"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
        />
        <circle cx="10" cy="15.5" r="0.8" fill="currentColor" />
      </svg>
      <svg
        v-else-if="status === 'UNAVAILABLE'"
        viewBox="0 0 20 20"
        fill="none"
        width="20"
        height="20"
      >
        <circle cx="10" cy="10" r="9" stroke="currentColor" stroke-width="1.4" />
        <path
          d="M7 7l6 6M13 7l-6 6"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
        />
      </svg>
      <svg v-else viewBox="0 0 20 20" fill="none" width="20" height="20">
        <circle
          cx="10"
          cy="10"
          r="9"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-dasharray="2 2"
        />
        <path
          d="M10 6v4M10 12.5v0.1"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
        />
      </svg>
    </div>
    <div class="banner-body">
      <div class="banner-title">
        {{ bannerTitle }}
      </div>
      <div v-for="(reason, i) in reasons" :key="i" class="banner-reason">
        {{ reason }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { AnalysisRunSummary } from "../../../api/task";

const props = defineProps<{ summary: AnalysisRunSummary }>();

const status = computed(() => props.summary.completeness.status);

const STATUS_TITLES: Record<string, string> = {
  COMPLETE: "分析完整",
  DEGRADED: "分析部分降级",
  UNAVAILABLE: "无可用分析结果",
  NOT_EVALUATED: "分析状态未知",
};

const bannerTitle = computed(() => STATUS_TITLES[status.value] || status.value);

const reasons = computed(() =>
  (props.summary.completeness.issues ?? []).map((i) => `${i.code}: ${i.message}`),
);

const bannerClass = computed(() => {
  switch (status.value) {
    case "COMPLETE":
      return "banner-ok";
    case "DEGRADED":
      return "banner-warn";
    case "UNAVAILABLE":
      return "banner-err";
    default:
      return "banner-muted";
  }
});
</script>

<style scoped>
.banner {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 100%;
  padding: 16px 18px;
  border-radius: var(--radius-md, 12px);
  margin-bottom: 0;
  font-size: 13px;
  box-shadow: var(--shadow-xs);
}

.banner-ok {
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}

.banner-warn {
  background: #fffbeb;
  color: #92400e;
  border: 1px solid #fde68a;
}

.banner-err {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.banner-muted {
  background: #f8fafc;
  color: #475569;
  border: 1px solid #e2e8f0;
}

.banner-icon {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  flex-shrink: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.62);
}

.banner-title {
  font-weight: 700;
  margin-bottom: 3px;
}

.banner-reason {
  font-size: 12px;
  opacity: 0.85;
}
</style>
