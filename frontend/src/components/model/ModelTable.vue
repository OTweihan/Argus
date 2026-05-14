<template>
  <el-table v-if="models.length" :data="models" stripe style="width:100%" :height="height">
    <el-table-column label="名称" min-width="160">
      <template #default="{ row }">
        <strong>{{ row.name }}</strong>
        <div style="color:#909399;font-size:12px">
          {{ row.modelConfigId }}
        </div>
      </template>
    </el-table-column>
    <el-table-column prop="provider" label="供应商" min-width="110" />
    <el-table-column prop="model" label="模型" min-width="100" />
    <el-table-column label="是否默认" width="180" align="center">
      <template #default="{ row }">
        <el-tag v-if="row.isDefault" type="warning" size="small" effect="plain">
          默认
        </el-tag>
        <span v-else style="color:#909399;font-size:13px">-</span>
      </template>
    </el-table-column>
    <el-table-column label="状态" width="200">
      <template #default="{ row }">
        {{ row.enabled ? "启用" : "停用" }} / Key {{
          row.apiKeySet ? "已配置" : "未配置"
        }}
      </template>
    </el-table-column>
    <el-table-column label="操作" width="300" fixed="right">
      <template #default="{ row }">
        <el-button @click="$emit('edit', row)">
          编辑
        </el-button>
        <el-button @click="$emit('test', row.modelConfigId)">
          测试
        </el-button>
        <el-button type="danger" @click="$emit('delete', row.modelConfigId)">
          删除
        </el-button>
      </template>
    </el-table-column>
  </el-table>
  <el-empty v-else description="暂无模型配置。" />
</template>

<script setup lang="ts">
import type {ModelConfig} from "../../types";

defineProps<{ models: ModelConfig[]; height?: string | number }>();
defineEmits<{ edit: [model: ModelConfig]; test: [modelConfigId: string]; delete: [modelConfigId: string] }>();
</script>
