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
        <div class="classpath-layout">
          <div
            class="classpath-status"
            :class="diagnostics.classpathAvailable ? 'available' : 'unavailable'"
          >
            <span class="classpath-status-icon" aria-hidden="true">
              <svg v-if="diagnostics.classpathAvailable" viewBox="0 0 20 20" fill="none">
                <circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.5" />
                <path
                  d="M6.5 10.2l2.2 2.2 4.8-5"
                  stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"
                />
              </svg>
              <svg v-else viewBox="0 0 20 20" fill="none">
                <circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.5" />
                <path d="M7.3 7.3l5.4 5.4m0-5.4l-5.4 5.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              </svg>
            </span>
            <span class="classpath-status-copy">
              <strong>{{ diagnostics.classpathAvailable ? "依赖环境可用" : "依赖环境不可用" }}</strong>
              <span>
                {{ diagnostics.classpathAvailable ? "可用于类型与符号解析" : "调用解析结果可能出现降级" }}
              </span>
            </span>
          </div>

          <div class="classpath-stat-grid">
            <div class="classpath-stat classpath-source-stat">
              <span class="stat-label">解析来源</span>
              <strong class="mono">{{ diagnostics.classpathSource || "未提供" }}</strong>
            </div>
            <div class="classpath-stat">
              <span class="stat-label">JAR 依赖</span>
              <strong>{{ diagnostics.jarCount }}</strong>
            </div>
            <div class="classpath-stat">
              <span class="stat-label">模块总数</span>
              <strong>{{ diagnostics.moduleCount }}</strong>
            </div>
            <div class="classpath-stat">
              <span class="stat-label">应用模块</span>
              <strong>{{ diagnostics.applicationModuleCount }}</strong>
            </div>
          </div>
        </div>

        <div
          v-if="(diagnostics.classpathWarnings ?? []).length || (diagnostics.classpathErrors ?? []).length"
          class="classpath-messages"
        >
          <div
            v-for="(w, i) in diagnostics.classpathWarnings ?? []"
            :key="`warning-${i}`" class="classpath-message warning"
          >
            <span class="message-icon">!</span>
            <span>{{ w }}</span>
          </div>
          <div
            v-for="(e, i) in diagnostics.classpathErrors ?? []"
            :key="`error-${i}`" class="classpath-message error"
          >
            <span class="message-icon">×</span>
            <span>{{ e }}</span>
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
  align-content: stretch;
  gap: 9px;
  height: 100%;
  min-height: 300px;
  padding: 0;
}

.diag-section {
  margin-bottom: 0;
  padding: 11px 14px;
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
  font-size: 14px;
  color: var(--text-strong);
  margin-bottom: 7px;
}

.source-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.source-stat {
  display: flex;
  align-items: flex-start;
  min-width: 0;
  padding: 7px 9px;
  flex-direction: column;
  gap: 2px;
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
  font-size: 18px;
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
  margin-bottom: 6px;
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
  font-size: 21px;
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
  font-size: 14px;
}

.distribution-bar {
  display: flex;
  width: 100%;
  height: 6px;
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
  gap: 6px;
  margin-top: 7px;
}

.call-stat {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr);
  align-items: center;
  gap: 5px 8px;
  min-height: 64px;
  padding: 9px 11px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: rgba(248, 250, 252, 0.76);
}

.call-stat .stat-label {
  font-size: 12px;
}

.call-stat strong {
  grid-column: 2;
  color: var(--text-strong);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 16px;
  line-height: 1.2;
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

.classpath-layout {
  display: grid;
  grid-template-columns: minmax(220px, 0.75fr) minmax(0, 2fr);
  align-items: stretch;
  gap: 7px;
}

.classpath-status {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 64px;
  padding: 9px 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
}

.classpath-status.available {
  border-color: rgba(10, 186, 181, 0.24);
  background: linear-gradient(145deg, var(--brand-50), rgba(255, 255, 255, 0.92));
}

.classpath-status.unavailable {
  border-color: var(--danger-line);
  background: linear-gradient(145deg, var(--danger-soft), rgba(255, 255, 255, 0.92));
}

.classpath-status-icon {
  display: inline-grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: var(--shadow-xs);
}

.classpath-status.available .classpath-status-icon {
  color: var(--brand-700);
}

.classpath-status.unavailable .classpath-status-icon {
  color: var(--danger);
}

.classpath-status-icon svg {
  width: 19px;
  height: 19px;
}

.classpath-status-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.classpath-status-copy strong {
  color: var(--text-strong);
  font-size: 13px;
}

.classpath-status-copy span {
  color: var(--text-faint);
  font-size: 11px;
  line-height: 1.5;
}

.classpath-stat-grid {
  display: grid;
  grid-template-columns: minmax(160px, 1.4fr) repeat(3, minmax(100px, 1fr));
  gap: 6px;
}

.classpath-stat {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  min-width: 0;
  min-height: 64px;
  padding: 8px 10px;
  flex-direction: column;
  gap: 3px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
}

.classpath-stat strong {
  width: 100%;
  overflow: hidden;
  color: var(--text-strong);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 17px;
  line-height: 1.25;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.classpath-source-stat strong {
  color: var(--brand-700);
  font-size: 12px;
}

.classpath-messages {
  display: grid;
  gap: 5px;
  margin-top: 7px;
}

.classpath-message {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 6px 9px;
  border: 1px solid;
  border-radius: var(--radius-sm);
  font-size: 12px;
  line-height: 1.55;
}

.classpath-message.warning {
  border-color: var(--warning-line);
  color: var(--warning);
  background: var(--warning-soft);
}

.classpath-message.error {
  border-color: var(--danger-line);
  color: var(--danger);
  background: var(--danger-soft);
}

.message-icon {
  display: inline-grid;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  place-items: center;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.72);
  font-size: 11px;
  font-weight: 800;
}

.diag-sub {
  margin-top: 4px;
  font-size: 12px;
}

.diag-failed-file {
  color: var(--text-faint);
  padding: 1px 0;
}

.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}

@media (max-width: 720px) {
  .diag-wrap {
    grid-template-columns: 1fr;
    align-content: start;
    min-height: 0;
  }

  .diag-section:last-of-type {
    grid-column: auto;
  }

  .source-stat-grid,
  .call-stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .classpath-layout {
    grid-template-columns: 1fr;
  }

  .classpath-stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 420px) {
  .source-stat-grid,
  .call-stat-grid,
  .classpath-stat-grid {
    grid-template-columns: 1fr;
  }
}
</style>
