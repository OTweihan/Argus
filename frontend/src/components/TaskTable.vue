<template>
  <div v-if="!tasks.length" class="empty">暂无任务</div>
  <div v-else class="table-wrap">
    <table>
      <thead>
      <tr>
        <th>目标</th>
        <th>状态</th>
        <th>项目</th>
        <th>步骤</th>
        <th>创建时间</th>
        <th>操作</th>
      </tr>
      </thead>
      <tbody>
      <tr v-for="task in tasks" :key="task.taskId">
        <td>
          <strong>{{ compact(task.goal, 52) }}</strong>
          <div class="muted mono">{{ task.taskId }}</div>
        </td>
        <td>
            <span class="pill" :class="taskDisplayStatus(task)">
              {{ taskDisplayStatus(task) }}
            </span>
        </td>
        <td>{{ projectName(task.projectId) }}</td>
        <td>{{ task.currentStep }}/{{ task.maxSteps }}</td>
        <td>{{ formatDate(task.createdAt) }}</td>
        <td class="actions">
          <button type="button" @click="$emit('select', task.taskId)">详情</button>
          <button
              class="primary"
              type="button"
              :disabled="!canStartTask(task)"
              @click="$emit('start', task.taskId)"
          >
            启动
          </button>
        </td>
      </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import type {Project, Task} from "../types";
import {canStartTask, compact, formatDate, taskDisplayStatus} from "../utils";

const props = defineProps<{
  tasks: Task[];
  projects: Project[];
}>();

defineEmits<{
  select: [taskId: string];
  start: [taskId: string];
}>();

function projectName(projectId: string | null): string {
  if (!projectId) return "-";
  return props.projects.find((project) => project.projectId === projectId)?.name ?? projectId;
}
</script>
