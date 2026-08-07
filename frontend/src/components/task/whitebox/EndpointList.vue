<template>
  <div class="list-wrap">
    <div class="list-toolbar">
      <el-input v-model="filter" placeholder="过滤路径" clearable class="filter-input" />
      <span v-if="total !== null" class="list-count">共 {{ total }} 个端点</span>
    </div>
    <el-table :data="filteredItems" size="small" stripe style="width: 100%">
      <el-table-column label="方法" width="70">
        <template #default="{ row }">
          <el-tag size="small" :type="httpMethodTag(row.httpMethod)">
            {{ row.httpMethod }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="路径" min-width="200">
        <template #default="{ row }">
          <span class="ep-path mono">{{ row.normalizedPath }}</span>
        </template>
      </el-table-column>
      <el-table-column label="Controller" min-width="180">
        <template #default="{ row }">
          <span class="mono">{{ row.controllerClass || "-" }}</span>
        </template>
      </el-table-column>
      <el-table-column label="方法" min-width="120">
        <template #default="{ row }">
          {{ row.controllerMethod || "-" }}
        </template>
      </el-table-column>
      <template #append>
        <InfiniteScrollLoad
          :has-more="hasMore"
          :loading="loading"
          @load-more="$emit('load-more')"
        />
      </template>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import type { EndpointInfo } from "../../../api/task";
import { httpMethodTag } from "../../../utils";
import InfiniteScrollLoad from "../../common/InfiniteScrollLoad.vue";

const props = defineProps<{
  items: EndpointInfo[];
  total: number | null;
  hasMore: boolean;
  loading: boolean;
}>();

defineEmits<{ "load-more": [] }>();

const filter = ref("");

const filteredItems = computed(() => {
  const q = filter.value.trim().toLowerCase();
  if (!q) return props.items;
  return props.items.filter(
    (e) =>
      e.normalizedPath.toLowerCase().includes(q) ||
      (e.controllerClass || "").toLowerCase().includes(q),
  );
});
</script>

<style scoped>
.list-wrap {
  padding: 2px 0;
}

.list-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: space-between;
  margin-bottom: 12px;
}

.filter-input {
  width: 280px;
  max-width: 100%;
}

.list-count {
  font-size: 12px;
  color: var(--text-faint);
}

.ep-path {
  font-size: 12px;
  color: var(--text-strong);
}

.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}

@media (max-width: 640px) {
  .list-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .filter-input {
    width: 100%;
  }
}
</style>
