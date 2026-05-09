<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('close')" title="任务详情" width="600px" align-center
             append-to-body>
    <div v-loading="loading" class="dialog-body">
      <TaskDetail v-if="task" :task="task" :projects="projects" :enabled-models="enabledModels"/>
      <el-empty v-else-if="!loading" description="未选择任务"/>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import type {ModelConfig, Project, Task} from "../../types";
import TaskDetail from "./TaskDetail.vue";

defineProps<{
  visible: boolean;
  task: Task | null;
  loading: boolean;
  projects: Project[];
  enabledModels: ModelConfig[];
}>();
defineEmits<{ close: [] }>();
</script>

<style scoped>
.dialog-body {
  min-height: 220px;
}
</style>
