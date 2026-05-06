<template>
  <div v-if="!models.length" class="empty">暂无模型配置。</div>
  <div v-else class="table-wrap">
    <table>
      <thead>
      <tr>
        <th>名称</th>
        <th>供应商</th>
        <th>模型</th>
        <th>作用域</th>
        <th>状态</th>
        <th>操作</th>
      </tr>
      </thead>
      <tbody>
      <tr v-for="model in models" :key="model.modelConfigId">
        <td>
          <strong>{{ model.name }}</strong>
          <div class="muted mono">{{ model.modelConfigId }}</div>
        </td>
        <td>{{ model.provider }}</td>
        <td>{{ model.model }}</td>
        <td>{{ model.taskType ?? "全局" }}{{ model.isDefault ? " / 默认" : "" }}</td>
        <td>{{ model.enabled ? "启用" : "停用" }} / Key {{ model.apiKeySet ? "已配置" : "未配置" }}</td>
        <td class="actions">
          <button type="button" @click="$emit('edit', model)">编辑</button>
          <button type="button" @click="$emit('test', model.modelConfigId)">测试</button>
          <button class="danger" type="button" @click="$emit('delete', model.modelConfigId)">
            删除
          </button>
        </td>
      </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import type {ModelConfig} from "../types";

defineProps<{
  models: ModelConfig[];
}>();

defineEmits<{
  edit: [model: ModelConfig];
  test: [modelConfigId: string];
  delete: [modelConfigId: string];
}>();
</script>
