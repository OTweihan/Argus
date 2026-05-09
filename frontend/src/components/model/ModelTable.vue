<template>
  <el-table v-if="models.length" :data="models" stripe style="width:100%" :height="height">
    <el-table-column label="名称" min-width="160">
      <template #default="{ row }">
        <strong>{{ row.name }}</strong>
        <div style="color:#909399;font-size:12px">{{ row.modelConfigId }}</div>
      </template>
    </el-table-column>
    <el-table-column prop="provider" label="供应商" width="110"/>
    <el-table-column prop="model" label="模型" width="180"/>
    <el-table-column label="作用域" width="120">
      <template #default="{ row }">{{ row.taskType ?? "全局" }}{{ row.isDefault ? " / 默认" : "" }}</template>
    </el-table-column>
    <el-table-column label="状态" width="140">
      <template #default="{ row }">{{ row.enabled ? "启用" : "停用" }} / Key {{
          row.apiKeySet ? "已配置" : "未配置"
        }}
      </template>
    </el-table-column>
    <el-table-column label="操作" width="200" fixed="right">
      <template #default="{ row }">
        <el-button size="small" @click="$emit('edit', row)">编辑</el-button>
        <el-button size="small" @click="$emit('test', row.modelConfigId)">测试</el-button>
        <el-button size="small" type="danger" @click="$emit('delete', row.modelConfigId)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
  <el-empty v-else description="暂无模型配置。"/>
</template>

<script setup lang="ts">
import type {ModelConfig} from "../../types";

defineProps<{ models: ModelConfig[]; height?: string | number }>();
defineEmits<{ edit: [model: ModelConfig]; test: [modelConfigId: string]; delete: [modelConfigId: string] }>();
</script>
