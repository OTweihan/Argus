<template>
  <div class="diag-wrap">
    <template v-if="diagnostics">
      <!-- 解析统计 -->
      <div class="diag-section">
        <div class="diag-title">源码解析</div>
        <div class="source-stat-grid">
          <div class="source-stat">
            <span class="stat-label">源文件总数</span>
            <strong class="stat-number">{{ diagnostics.totalSourceFiles }}</strong>
          </div>
          <div class="source-stat">
            <span class="stat-label">可分析文件</span>
            <strong class="stat-number">{{ diagnostics.eligibleSourceFiles }}</strong>
          </div>
          <div class="source-stat source-stat-ok">
            <span class="stat-label">已解析</span>
            <strong class="stat-number">{{ diagnostics.parsedFileCount }}</strong>
          </div>
          <div class="source-stat" :class="{ 'source-stat-warn': diagnostics.failedFileCount > 0 }">
            <span class="stat-label">解析失败</span>
            <strong class="stat-number">{{ diagnostics.failedFileCount }}</strong>
          </div>
        </div>
        <div v-if="(diagnostics.failedFiles ?? []).length" class="diag-sub">
          <div v-for="f in diagnostics.failedFiles ?? []" :key="f" class="diag-failed-file mono">
            {{ f }}
          </div>
        </div>
      </div>

      <!-- 调用解析 -->
      <div class="diag-section">
        <div class="diag-title">调用解析</div>
        <div class="call-summary">
          <div class="call-total">
            <span class="stat-label">调用总数</span>
            <strong>{{ diagnostics.totalCalls }}</strong>
          </div>
          <div class="call-resolution-rate">
            <span class="rate-label">已解析 {{ resolvedCount }} 条</span>
            <strong>{{ resolvedRate }}%</strong>
          </div>
        </div>
        <div class="distribution-bar" aria-label="调用解析置信度分布">
          <span
            class="segment segment-high"
            :style="{ width: percentage(diagnostics.resolvedHigh) }"
          />
          <span
            class="segment segment-medium"
            :style="{ width: percentage(diagnostics.resolvedMedium) }"
          />
          <span
            class="segment segment-low"
            :style="{ width: percentage(diagnostics.resolvedLow) }"
          />
          <span
            class="segment segment-unresolved"
            :style="{ width: percentage(diagnostics.unresolved) }"
          />
        </div>
        <div class="call-stat-grid">
          <div class="call-stat high">
            <span class="stat-dot" />
            <span class="stat-label">高置信度</span>
            <strong>{{ diagnostics.resolvedHigh }}</strong>
          </div>
          <div class="call-stat medium">
            <span class="stat-dot" />
            <span class="stat-label">中置信度</span>
            <strong>{{ diagnostics.resolvedMedium }}</strong>
          </div>
          <div class="call-stat low">
            <span class="stat-dot" />
            <span class="stat-label">低置信度</span>
            <strong>{{ diagnostics.resolvedLow }}</strong>
          </div>
          <div class="call-stat unresolved">
            <span class="stat-dot" />
            <span class="stat-label">未解析</span>
            <strong>{{ diagnostics.unresolved }}</strong>
          </div>
        </div>
      </div>

      <!-- Classpath -->
      <div class="diag-section">
        <div class="diag-title">Classpath</div>
        <div class="diag-row">
          <span class="diag-key">可用</span>
          <span class="diag-val">{{ diagnostics.classpathAvailable ? "是" : "否" }}</span>
        </div>
        <div class="diag-row">
          <span class="diag-key">JAR 数量</span>
          <span class="diag-val">{{ diagnostics.jarCount }}</span>
        </div>
        <div v-if="diagnostics.classpathSource" class="diag-row">
          <span class="diag-key">来源</span>
          <span class="diag-val mono">{{ diagnostics.classpathSource }}</span>
        </div>
        <div v-if="diagnostics.moduleCount" class="diag-row">
          <span class="diag-key">模块数</span>
          <span class="diag-val"
            >{{ diagnostics.moduleCount }}（应用: {{ diagnostics.applicationModuleCount }}）</span
          >
        </div>
        <div v-if="(diagnostics.classpathWarnings ?? []).length" class="diag-sub">
          <div v-for="(w, i) in diagnostics.classpathWarnings ?? []" :key="i" class="diag-warn">
            {{ w }}
          </div>
        </div>
        <div v-if="(diagnostics.classpathErrors ?? []).length" class="diag-sub">
          <div v-for="(e, i) in diagnostics.classpathErrors ?? []" :key="i" class="diag-err">
            {{ e }}
          </div>
        </div>
      </div>
    </template>
    <el-empty v-else description="诊断数据不可用" :image-size="60" />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { DiagnosticsInfo } from "../../../api/task";

const props = defineProps<{ diagnostics: DiagnosticsInfo | null }>();

const resolvedCount = computed(() =>
  props.diagnostics ? Math.max(0, props.diagnostics.totalCalls - props.diagnostics.unresolved) : 0,
);

const resolvedRate = computed(() => {
  if (!props.diagnostics?.totalCalls) return 0;
  return Math.round((resolvedCount.value / props.diagnostics.totalCalls) * 100);
});

function percentage(value: number): string {
  if (!props.diagnostics?.totalCalls) return "0%";
  return `${Math.max(0, (value / props.diagnostics.totalCalls) * 100)}%`;
}
</script>

<style scoped>
.diag-wrap {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 2px 0;
}

.diag-section {
  margin-bottom: 0;
  padding: 16px 18px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
  background: var(--surface-glass-strong);
  box-shadow: var(--shadow-xs);
}

.diag-section:last-of-type {
  grid-column: 1 / -1;
}

.diag-title {
  font-weight: 700;
  font-size: 15px;
  color: var(--text-strong);
  margin-bottom: 10px;
}

.source-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.source-stat {
  display: flex;
  align-items: flex-start;
  min-width: 0;
  padding: 10px 12px;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  text-align: left;
}

.stat-label {
  color: var(--text-faint);
  font-size: 11px;
  font-weight: 600;
}

.stat-number {
  width: 100%;
  color: var(--text-strong);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 20px;
  line-height: 1.2;
  text-align: left;
}

.source-stat-ok .stat-number {
  color: var(--brand-700);
}

.source-stat-warn {
  border-color: var(--warning-line);
  background: var(--warning-soft);
}

.source-stat-warn .stat-number {
  color: var(--warning);
}

.call-summary {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.call-total,
.call-resolution-rate {
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  gap: 2px;
}

.call-total strong {
  color: var(--text-strong);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 24px;
  line-height: 1.15;
}

.call-resolution-rate {
  align-items: flex-end;
}

.rate-label {
  color: var(--text-faint);
  font-size: 11px;
}

.call-resolution-rate strong {
  color: var(--brand-700);
  font-size: 16px;
}

.distribution-bar {
  display: flex;
  width: 100%;
  height: 8px;
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: var(--surface-muted);
}

.segment {
  min-width: 0;
  height: 100%;
}

.segment-high {
  background: #0f9f75;
}
.segment-medium {
  background: #e6a23c;
}
.segment-low {
  background: #60a5fa;
}
.segment-unresolved {
  background: #e56b4a;
}

.call-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.call-stat {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr);
  align-items: center;
  gap: 3px 7px;
  padding: 9px 10px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: rgba(248, 250, 252, 0.76);
}

.call-stat strong {
  grid-column: 2;
  color: var(--text-strong);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 15px;
}

.call-stat.unresolved strong {
  color: #c2410c;
}

.stat-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.call-stat.high .stat-dot {
  background: #0f9f75;
}
.call-stat.medium .stat-dot {
  background: #e6a23c;
}
.call-stat.low .stat-dot {
  background: #60a5fa;
}
.call-stat.unresolved .stat-dot {
  background: #e56b4a;
}

.diag-row {
  font-size: 13px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  padding: 4px 0;
}

.diag-key {
  color: var(--text-faint);
  min-width: 60px;
}

.diag-val {
  color: var(--text-strong);
  font-weight: 600;
}

.diag-val.warn {
  color: #c2410c;
}

.diag-val.ok {
  color: #059669;
}

.diag-sub {
  margin-top: 4px;
  font-size: 12px;
}

.diag-failed-file {
  color: var(--text-faint);
  padding: 1px 0;
}

.diag-warn {
  color: #b45309;
}

.diag-err {
  color: #dc2626;
}

.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}

@media (max-width: 720px) {
  .diag-wrap {
    grid-template-columns: 1fr;
  }

  .diag-section:last-of-type {
    grid-column: auto;
  }

  .source-stat-grid,
  .call-stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 420px) {
  .source-stat-grid,
  .call-stat-grid {
    grid-template-columns: 1fr;
  }
}
</style>
