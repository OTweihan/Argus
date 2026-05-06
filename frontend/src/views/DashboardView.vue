<template>
  <section class="grid metrics">
    <div class="metric"><strong>{{ projects.length }}</strong><span>项目</span></div>
    <div class="metric"><strong>{{ allTasks.length }}</strong><span>任务</span></div>
    <div class="metric"><strong>{{ runningCount }}</strong><span>运行中</span></div>
    <div class="metric"><strong>{{ findingCount }}</strong><span>问题</span></div>
  </section>
  <section class="panel with-margin">
    <h2>最近任务</h2>
    <TaskTable
        :tasks="recentTasks"
        :projects="projects"
        @select="selectTask"
        @start="startTask"
    />
  </section>
</template>

<script setup lang="ts">
import TaskTable from "../components/TaskTable.vue";
import { useConsoleApp } from "../composables/useConsoleApp";

type AppContext = ReturnType<typeof useConsoleApp>;

const props = defineProps<{ app: AppContext }>();
const { projects, allTasks, recentTasks, runningCount, findingCount, selectTask, startTask } = props.app;
</script>
