<template>
  <div v-if="!projects.length" class="empty">暂无项目</div>
  <div v-else class="table-wrap">
    <table>
      <thead>
      <tr>
        <th>名称</th>
        <th>基础 URL</th>
        <th>默认值</th>
        <th>更新时间</th>
        <th>操作</th>
      </tr>
      </thead>
      <tbody>
      <tr v-for="project in projects" :key="project.projectId">
        <td>
          <strong>{{ project.name }}</strong>
          <div class="muted mono">{{ project.projectId }}</div>
        </td>
        <td>{{ project.baseUrl ?? "-" }}</td>
        <td>{{ project.defaultMaxSteps ?? "-" }} 步 / {{ project.defaultTimeoutSeconds ?? "-" }} 秒</td>
        <td>{{ formatDate(project.updatedAt) }}</td>
        <td class="actions">
          <button type="button" @click="$emit('edit', project)">编辑</button>
          <button class="danger" type="button" @click="$emit('delete', project.projectId)">
            删除
          </button>
        </td>
      </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import type {Project} from "../types";
import {formatDate} from "../utils";

defineProps<{
  projects: Project[];
}>();

defineEmits<{
  edit: [project: Project];
  delete: [projectId: string];
}>();
</script>
