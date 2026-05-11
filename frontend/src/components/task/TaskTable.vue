<template>
  <el-table v-if="tasks.length" :data="tasks" stripe style="width:100%" :height="height">
    <el-table-column label="任务名称" min-width="240">
      <template #default="{ row }">
        <strong>{{ row.name || "-" }}</strong>
        <div style="color:#909399;font-size:12px">{{ row.taskId }}</div>
      </template>
    </el-table-column>
    <el-table-column label="目标" min-width="300">
      <template #default="{ row }">
        <strong>{{ compact(row.goal, 52) }}</strong>
      </template>
    </el-table-column>
    <el-table-column label="状态" min-width="120">
      <template #default="{ row }">
        <el-tag :type="tagType(row)">{{ taskDisplayStatus(row) }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="项目" min-width="200">
      <template #default="{ row }">{{ projectName(row.projectId) }}</template>
    </el-table-column>
    <el-table-column label="步骤" min-width="100">
      <template #default="{ row }">{{ row.currentStep }}/{{ row.maxSteps }}</template>
    </el-table-column>
    <el-table-column label="创建时间" width="200">
      <template #default="{ row }">{{ formatDate(row.createdAt) }}</template>
    </el-table-column>
    <el-table-column label="操作" width="430" fixed="right">
      <template #default="{ row }">
        <el-button @click="$emit('select', row.taskId)">任务详情</el-button>
        <el-button v-if="props.showReport" :disabled="!row.reportPath" @click="$emit('report', row.taskId)">报告详情
        </el-button>
        <el-button v-if="props.showEdit" :disabled="!canEditTask(row)" @click="$emit('edit', row)">编辑</el-button>
        <el-button v-if="props.showDelete" type="danger" :disabled="!canDeleteTask(row)" @click="$emit('delete', row)">
          删除
        </el-button>
        <el-button v-if="canStartTask(row)" type="primary" @click="$emit('start', row.taskId)">启动</el-button>
        <el-button v-else-if="canRestartTask(row)" type="primary" @click="$emit('restart', row.taskId)">重试</el-button>
      </template>
    </el-table-column>
  </el-table>
  <el-empty v-else description="暂无任务"/>
</template>

<script setup lang="ts">
import type {Project, Task} from "../../types";
import {canRestartTask, canStartTask, compact, formatDate, taskDisplayStatus} from "../../utils";

const props = withDefaults(
    defineProps<{
      tasks: Task[];
      projects: Project[];
      height?: string | number;
      showEdit?: boolean;
      showReport?: boolean;
      showDelete?: boolean;
    }>(),
    {showEdit: true, showReport: true, showDelete: true},
);
defineEmits<{
  select: [taskId: string];
  report: [taskId: string];
  edit: [task: Task];
  delete: [task: Task];
  start: [taskId: string];
  restart: [taskId: string];
}>();

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

function canEditTask(task: Task): boolean {
  return task.status === "pending" && !task.schedulerStatus;
}

function canDeleteTask(task: Task): boolean {
  return task.status === "pending" && !task.schedulerStatus;
}
</script>
