<template>
  <div class="diagnostics-view">
    <section class="page-intro">
      <div>
        <p class="eyebrow">OBSERVABILITY</p>
        <h2>诊断中心</h2>
        <p class="intro-copy">集中检查服务健康度、运行日志与请求链路。</p>
      </div>
      <div class="intro-mark" aria-hidden="true"><span></span><span></span><span></span></div>
    </section>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="当前数据范围"
      description="已接入 Python 结构化日志与本地开发会话；Java 日志和跨服务 Request ID 链路仍在逐步接入。"
      class="phase-tip"
    />
    <el-tabs v-model="activeTab" class="diagnostics-tabs">
      <el-tab-pane label="服务状态" name="services">
        <ServicesPanel v-if="activeTab === 'services'" />
      </el-tab-pane>
      <el-tab-pane label="运行日志" name="logs" lazy>
        <LogsPanel v-if="activeTab === 'logs'" />
      </el-tab-pane>
      <el-tab-pane label="请求追踪" name="trace" lazy>
        <TracePanel v-if="activeTab === 'trace'" />
      </el-tab-pane>
      <el-tab-pane label="启动会话" name="runs" lazy>
        <RunsPanel v-if="activeTab === 'runs'" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";

import ServicesPanel from "./ServicesPanel.vue";
import LogsPanel from "./LogsPanel.vue";
import TracePanel from "./TracePanel.vue";
import RunsPanel from "./RunsPanel.vue";

const activeTab = ref("services");
</script>

<style scoped>
.diagnostics-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 4px 0 8px;
  overflow: auto;
}

.page-intro {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 112px;
  padding: 22px 26px;
  border: 1px solid rgba(10, 186, 181, 0.18);
  border-radius: var(--radius-md);
  background:
    radial-gradient(circle at 88% 30%, rgba(56, 189, 248, 0.15), transparent 34%),
    var(--surface-glass-strong);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(var(--blur-soft));
}

.eyebrow {
  margin: 0 0 5px;
  color: var(--brand-600);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
}

.page-intro h2 {
  margin: 0;
  color: var(--text-strong);
  font-size: 24px;
  line-height: 1.25;
}

.intro-copy {
  margin: 7px 0 0;
  color: var(--text-faint);
  font-size: 13px;
}

.intro-mark {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 5px;
  width: 58px;
  height: 58px;
  padding-bottom: 15px;
  border: 1px solid rgba(10, 186, 181, 0.22);
  border-radius: 18px;
  background: var(--brand-gradient-soft);
  box-shadow: var(--shadow-xs);
}

.intro-mark span {
  width: 5px;
  border-radius: 4px;
  background: var(--brand-gradient-strong);
}

.intro-mark span:nth-child(1) {
  height: 12px;
}
.intro-mark span:nth-child(2) {
  height: 24px;
}
.intro-mark span:nth-child(3) {
  height: 18px;
}

.phase-tip {
  border-radius: var(--radius-md);
  border-color: var(--info-line);
}

.diagnostics-tabs {
  padding: 0 20px 20px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
  background: var(--surface-glass-strong);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(var(--blur-soft));
}

.diagnostics-tabs :deep(.el-tabs__header) {
  margin-bottom: 18px;
}

.diagnostics-tabs :deep(.el-tabs__item) {
  height: 54px;
  padding: 0 22px;
  font-weight: 650;
}

.diagnostics-tabs :deep(.el-tabs__content) {
  overflow: visible;
}

@media (max-width: 720px) {
  .page-intro {
    padding: 18px;
  }

  .intro-mark {
    display: none;
  }

  .diagnostics-tabs {
    padding-inline: 14px;
  }

  .diagnostics-tabs :deep(.el-tabs__item) {
    padding: 0 12px;
  }
}
</style>
