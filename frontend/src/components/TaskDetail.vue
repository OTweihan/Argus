<template>
  <div class="detail">
    <div class="detail-toolbar">
      <el-tag :type="tagType" size="small">{{ taskDisplayStatus(task) }}</el-tag>
      <code class="mono">{{ task.taskId }}</code>
      <el-button v-if="!task.reportPath" disabled size="small">HTML 报告</el-button>
      <el-button v-if="!task.reportPath" disabled size="small">JSON 报告</el-button>
      <el-button v-if="task.reportPath" size="small" @click="openReport(false)">HTML 报告</el-button>
      <el-button v-if="task.reportPath" size="small" @click="openReport(true)">JSON 报告</el-button>
    </div>
    <div class="detail-goal">{{ task.goal }}</div>
    <div class="detail-desc muted">{{ task.resultSummary ?? task.errorMessage ?? "" }}</div>
    <el-row :gutter="16">
      <el-col :span="12">
        <h3>步骤日志</h3>
        <div v-if="task.logs.length" class="log-list">
          <el-card v-for="log in task.logs" :key="log.taskLogId" shadow="hover" class="log-card">
            <div class="log-title">
              <strong>#{{ log.stepNumber }} {{ log.action }}</strong>
              <el-tag :type="log.result === 'success' ? 'success' : 'danger'" size="small">{{ log.result }}</el-tag>
            </div>
            <div class="muted">{{ log.message ?? log.error ?? "" }}</div>
            <div class="mono muted" style="font-size:11px">{{ log.urlAfter ?? log.urlBefore ?? "" }}</div>
          </el-card>
        </div>
        <el-empty v-else description="暂无日志" />
      </el-col>
      <el-col :span="12">
        <h3>问题</h3>
        <div v-if="task.findings.length" class="finding-list">
          <el-card v-for="finding in task.findings" :key="finding.findingId" shadow="hover" class="log-card">
            <div class="log-title">
              <strong>{{ finding.title }}</strong>
              <el-tag :type="findingTagType(finding.severity)" size="small">{{ finding.severity }}</el-tag>
            </div>
            <div>{{ finding.description }}</div>
            <div class="mono muted" style="font-size:11px">{{ finding.url ?? "" }}</div>
          </el-card>
        </div>
        <el-empty v-else description="暂无问题" />
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import {computed} from "vue";
import {reportUrl} from "../api";
import type {Task, FindingSeverity} from "../types";
import {taskDisplayStatus} from "../utils";

const props = defineProps<{ task: Task }>();

const tagType = computed(() => {
  const s = taskDisplayStatus(props.task);
  if (s === "completed") return "success";
  if (s === "failed" || s === "timeout" || s === "cancelled") return "danger";
  if (s === "running" || s === "queued") return "warning";
  return "info";
});

function findingTagType(severity: FindingSeverity): string {
  if (severity === "high" || severity === "critical") return "danger";
  if (severity === "medium") return "warning";
  return "info";
}

function openReport(json: boolean): void {
  window.open(reportUrl(props.task.taskId, json), "_blank");
}
</script>

<style scoped>
.detail { display: grid; gap: 14px; }
.detail-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.detail-goal { font-weight: 600; font-size: 15px; }
.detail-desc { font-size: 13px; }
.log-list, .finding-list { display: grid; gap: 10px; max-height: 420px; overflow: auto; }
.log-card { cursor: default; }
.log-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 6px; }
.log-title strong { font-size: 13px; }
.muted { color: #909399; }
.mono { font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace; }
</style>
