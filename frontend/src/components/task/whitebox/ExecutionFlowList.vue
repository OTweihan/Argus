<template>
  <div class="list-wrap">
    <el-collapse v-if="items.length">
      <el-collapse-item
        v-for="flow in items" :key="flow.executionFlowId"
        :title="flow.entryPoint"
      >
        <div class="flow-depth">
          调用深度: {{ flow.callDepth }}
        </div>
        <el-table :data="flow.steps" size="small" stripe style="width:100%" :max-height="isLarge ? 300 : undefined">
          <el-table-column label="#" width="40">
            <template #default="{ row }">
              {{ row.stepIndex }}
            </template>
          </el-table-column>
          <el-table-column label="深度" width="50">
            <template #default="{ row }">
              {{ row.depth }}
            </template>
          </el-table-column>
          <el-table-column label="方法" min-width="280">
            <template #default="{ row }">
              <span class="mono">{{ row.className || "-" }}.{{ row.methodName || row.methodKey }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>

    <el-empty v-else description="无执行流数据" :image-size="60" />

    <InfiniteScrollLoad :has-more="hasMore" :loading="loading" @load-more="$emit('load-more')" />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { ExecutionFlowInfo } from "../../../api/task";
import InfiniteScrollLoad from "../../common/InfiniteScrollLoad.vue";

const props = defineProps<{
  items: ExecutionFlowInfo[];
  hasMore: boolean;
  loading: boolean;
}>();

defineEmits<{ "load-more": [] }>();

const isLarge = computed(() => props.items.length > 3);
</script>

<style scoped>
.list-wrap {
  padding: 4px 0;
}

.flow-depth {
  font-size: 12px;
  color: var(--text-faint);
  margin-bottom: 8px;
}

.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}
</style>
