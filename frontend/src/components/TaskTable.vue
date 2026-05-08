<template>
  <el-table v-if="tasks.length" :data="tasks" stripe style="width:100%">
    <el-table-column label="目标" min-width="200">
      <template #default="{ row }">
        <strong>{{ compact(row.goal, 52) }}</strong>
        <div style="color:#909399;font-size:12px">{{ row.taskId }}</div>
      </template>
    </el-table-column>
    <el-table-column label="状态" width="110">
      <template #default="{ row }">
        <el-tag :type="tagType(row)" size="small">{{ taskDisplayStatus(row) }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="项目" width="130">
      <template #default="{ row }">{{ projectName(row.projectId) }}</template>
    </el-table-column>
    <el-table-column label="步骤" width="80">
      <template #default="{ row }">{{ row.currentStep }}/{{ row.maxSteps }}</template>
    </el-table-column>
    <el-table-column label="创建时间" width="120">
      <template #default="{ row }">{{ formatDate(row.createdAt) }}</template>
    </el-table-column>
    <el-table-column label="操作" width="140" fixed="right">
      <template #default="{ row }">
        <el-button size="small" @click="$emit('select', row.taskId)">详情</el-button>
        <el-button size="small" type="primary" :disabled="!canStartTask(row)" @click="$emit('start', row.taskId)">启动</el-button>
      </template>
    </el-table-column>
  </el-table>
  <el-empty v-else description="暂无任务" />
</template>

<script setup lang="ts">
import type {Project, Task, TaskDisplayStatus} from "../types";
import {canStartTask, compact, formatDate, taskDisplayStatus} from "../utils";

const props = defineProps<{ tasks: Task[]; projects: Project[] }>();
defineEmits<{ select: [taskId: string]; start: [taskId: string] }>();

function projectName(projectId: string | null): string {
  if (!projectId) return "-";
  return props.projects.find((p) => p.projectId === projectId)?.name ?? projectId;
}

function tagType(task: Task): string {
  const status = taskDisplayStatus(task);
  if (status === "completed") return "success";
  if (status === "failed" || status === "timeout" || status === "cancelled") return "danger";
  if (status === "running" || status === "queued") return "warning";
  return "info";
}
</script>
