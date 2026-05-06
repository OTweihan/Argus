<template>
  <div class="detail">
    <div class="actions">
      <span class="pill" :class="taskDisplayStatus(task)">{{ taskDisplayStatus(task) }}</span>
      <span class="mono">{{ task.taskId }}</span>
      <button v-if="!task.reportPath" type="button" disabled>HTML 报告</button>
      <button v-if="!task.reportPath" type="button" disabled>JSON 报告</button>
      <a v-if="task.reportPath" :href="reportUrl(task.taskId)" target="_blank" rel="noreferrer">
        <button type="button">HTML 报告</button>
      </a>
      <a v-if="task.reportPath" :href="reportUrl(task.taskId, true)" target="_blank" rel="noreferrer">
        <button type="button">JSON 报告</button>
      </a>
    </div>
    <div><strong>{{ task.goal }}</strong></div>
    <div class="muted">{{ task.resultSummary ?? task.errorMessage ?? "" }}</div>
    <div class="grid two">
      <div>
        <h2>步骤日志</h2>
        <div v-if="task.logs.length" class="log-list">
          <div v-for="log in task.logs" :key="log.taskLogId" class="item-card">
            <div class="item-title">
              <strong>#{{ log.stepNumber }} {{ log.action }}</strong>
              <span class="pill" :class="log.result">{{ log.result }}</span>
            </div>
            <div class="muted">{{ log.message ?? log.error ?? "" }}</div>
            <div class="mono muted">{{ log.urlAfter ?? log.urlBefore ?? "" }}</div>
          </div>
        </div>
        <div v-else class="empty">暂无日志</div>
      </div>
      <div>
        <h2>问题</h2>
        <div v-if="task.findings.length" class="finding-list">
          <div v-for="finding in task.findings" :key="finding.findingId" class="item-card">
            <div class="item-title">
              <strong>{{ finding.title }}</strong>
              <span class="pill" :class="finding.severity">{{ finding.severity }}</span>
            </div>
            <div>{{ finding.description }}</div>
            <div class="mono muted">{{ finding.url ?? "" }}</div>
          </div>
        </div>
        <div v-else class="empty">暂无问题</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import {reportUrl} from "../api";
import type {Task} from "../types";
import {taskDisplayStatus} from "../utils";

defineProps<{
  task: Task;
}>();
</script>
