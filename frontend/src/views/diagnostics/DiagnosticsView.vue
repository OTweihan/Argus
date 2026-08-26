<template>
  <div class="diagnostics-view">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="第一阶段仅本地文件数据源：Python 结构化日志 + dev 会话日志；requestId 链路贯通与 Java JSONL 化在日志基础规范阶段交付。"
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
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.phase-tip {
  border-radius: 10px;
}

.diagnostics-tabs :deep(.el-tabs__content) {
  overflow: visible;
}
</style>
