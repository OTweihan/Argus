<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('close')" title="报告详情" width="1180px" align-center
             append-to-body>
    <div class="report-toolbar">
      <el-button :disabled="!task?.reportPath" @click="openHtmlReport">查看 HTML 报告</el-button>
      <el-button :disabled="!task?.reportPath" @click="downloadHtmlReport">下载 HTML 报告</el-button>
      <el-button :disabled="!task?.reportPath" @click="downloadJsonReport">下载 JSON 报告</el-button>
    </div>
    <div class="report-dialog-body">
      <ReportView :report="report" :loading="loading" :task-id="task?.taskId ?? ''"/>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import {reportUrl} from "../../api";
import type {ReportData, Task} from "../../types";
import ReportView from "../../views/ReportView.vue";

const props = defineProps<{
  visible: boolean;
  task: Task | null;
  report: ReportData | null;
  loading: boolean;
}>();

defineEmits<{ close: [] }>();

function openHtmlReport(): void {
  if (props.task?.reportPath) {
    window.open(reportUrl(props.task.taskId), "_blank");
  }
}

function downloadHtmlReport(): void {
  if (props.task?.reportPath) {
    window.open(reportUrl(props.task.taskId, false, true), "_blank");
  }
}

function downloadJsonReport(): void {
  if (props.task?.reportPath) {
    window.open(reportUrl(props.task.taskId, true, true), "_blank");
  }
}
</script>

<style scoped>
.report-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.report-dialog-body {
  height: 72vh;
  min-height: 420px;
  display: flex;
  overflow: hidden;
  border: 1px solid #e4ebee;
  border-radius: 8px;
}
</style>
