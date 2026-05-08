<template>
  <el-table v-if="projects.length" :data="projects" stripe style="width:100%">
    <el-table-column label="名称" min-width="180">
      <template #default="{ row }">
        <strong>{{ row.name }}</strong>
        <div style="color:#909399;font-size:12px">{{ row.projectId }}</div>
      </template>
    </el-table-column>
    <el-table-column prop="baseUrl" label="基础 URL" min-width="200">
      <template #default="{ row }">{{ row.baseUrl ?? "-" }}</template>
    </el-table-column>
    <el-table-column label="默认值" width="160">
      <template #default="{ row }">{{ row.defaultMaxSteps ?? "-" }} 步 / {{ row.defaultTimeoutSeconds ?? "-" }} 秒</template>
    </el-table-column>
    <el-table-column label="更新时间" width="140">
      <template #default="{ row }">{{ formatDate(row.updatedAt) }}</template>
    </el-table-column>
    <el-table-column label="操作" width="140" fixed="right">
      <template #default="{ row }">
        <el-button size="small" @click="$emit('edit', row)">编辑</el-button>
        <el-button size="small" type="danger" @click="$emit('delete', row.projectId)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
  <el-empty v-else description="暂无项目" />
</template>

<script setup lang="ts">
import type {Project} from "../types";
import {formatDate} from "../utils";

defineProps<{ projects: Project[] }>();
defineEmits<{ edit: [project: Project]; delete: [projectId: string] }>();
</script>
