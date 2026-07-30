<template>
  <div class="diag-wrap">
    <template v-if="diagnostics">
      <!-- 解析统计 -->
      <div class="diag-section">
        <div class="diag-title">
          源码解析
        </div>
        <div class="diag-row">
          <span class="diag-key">源文件总数</span>
          <span class="diag-val">{{ diagnostics.totalSourceFiles }}</span>
        </div>
        <div class="diag-row">
          <span class="diag-key">可分析文件</span>
          <span class="diag-val">{{ diagnostics.eligibleSourceFiles }}</span>
        </div>
        <div class="diag-row">
          <span class="diag-key">已解析</span>
          <span class="diag-val">{{ diagnostics.parsedFileCount }}</span>
        </div>
        <div class="diag-row">
          <span class="diag-key">解析失败</span>
          <span class="diag-val" :class="{ warn: diagnostics.failedFileCount > 0 }">{{ diagnostics.failedFileCount }}</span>
        </div>
        <div v-if="(diagnostics.failedFiles ?? []).length" class="diag-sub">
          <div v-for="f in (diagnostics.failedFiles ?? [])" :key="f" class="diag-failed-file mono">
            {{ f }}
          </div>
        </div>
      </div>

      <!-- 调用解析 -->
      <div class="diag-section">
        <div class="diag-title">
          调用解析
        </div>
        <div class="diag-row">
          <span class="diag-key">总计</span>
          <span class="diag-val">{{ diagnostics.totalCalls }}</span>
          <span class="diag-key">高</span>
          <span class="diag-val ok">{{ diagnostics.resolvedHigh }}</span>
          <span class="diag-key">中</span>
          <span class="diag-val">{{ diagnostics.resolvedMedium }}</span>
          <span class="diag-key">低</span>
          <span class="diag-val">{{ diagnostics.resolvedLow }}</span>
          <span class="diag-key">未解析</span>
          <span class="diag-val" :class="{ warn: diagnostics.unresolved > 0 }">{{ diagnostics.unresolved }}</span>
        </div>
      </div>

      <!-- Classpath -->
      <div class="diag-section">
        <div class="diag-title">
          Classpath
        </div>
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
          <span class="diag-val">{{ diagnostics.moduleCount }}（应用: {{ diagnostics.applicationModuleCount }}）</span>
        </div>
        <div v-if="(diagnostics.classpathWarnings ?? []).length" class="diag-sub">
          <div v-for="(w, i) in (diagnostics.classpathWarnings ?? [])" :key="i" class="diag-warn">
            {{ w }}
          </div>
        </div>
        <div v-if="(diagnostics.classpathErrors ?? []).length" class="diag-sub">
          <div v-for="(e, i) in (diagnostics.classpathErrors ?? [])" :key="i" class="diag-err">
            {{ e }}
          </div>
        </div>
      </div>
    </template>
    <el-empty v-else description="诊断数据不可用" :image-size="60" />
  </div>
</template>

<script setup lang="ts">
import type { DiagnosticsInfo } from "../../../api/task";

defineProps<{ diagnostics: DiagnosticsInfo | null }>();
</script>

<style scoped>
.diag-wrap {
  padding: 4px 0;
}

.diag-section {
  margin-bottom: 14px;
  padding: 10px 14px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: var(--surface-glass-strong);
}

.diag-title {
  font-weight: 700;
  font-size: 13px;
  color: var(--text-strong);
  margin-bottom: 6px;
}

.diag-row {
  font-size: 13px;
  display: flex;
  gap: 6px;
  padding: 2px 0;
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
</style>
