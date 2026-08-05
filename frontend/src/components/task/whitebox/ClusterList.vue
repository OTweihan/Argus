<template>
  <div class="cluster-list">
    <div class="list-header">
      <span v-if="total !== null" class="total">
        共 {{ total }} 个聚类
      </span>
    </div>

    <div v-if="loading && !items.length" v-loading="loading" class="skeleton" />

    <template v-if="items.length">
      <details
        v-for="c in items"
        :key="c.clusterId"
        class="cluster-item"
      >
        <summary class="cluster-summary">
          <strong>{{ c.suggestedLabel || "(未命名)" }}</strong>
          <span class="badge">{{ c.memberCount }} members</span>
        </summary>
        <ul class="member-keys">
          <li v-for="key in c.memberKeys" :key="key">
            <code>{{ key }}</code>
          </li>
        </ul>
      </details>
    </template>

    <el-empty v-else-if="!loading" description="该分析执行未生成功能聚类" />

    <InfiniteScrollLoad :has-more="hasMore" :loading="loading" @load-more="$emit('load-more')" />
  </div>
</template>

<script setup lang="ts">
import type { ClusterInfo } from "../../../api/task";
import InfiniteScrollLoad from "../../common/InfiniteScrollLoad.vue";

defineProps<{
  items: ClusterInfo[];
  total: number | null;
  hasMore: boolean;
  loading: boolean;
}>();

defineEmits<{
  (e: "load-more"): void;
}>();
</script>

<style scoped>
.cluster-list {
  padding: 4px 0;
}

.list-header {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}

.total {
  font-size: 13px;
  color: var(--text-faint);
}

.cluster-item {
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  margin-bottom: 10px;
  background: var(--surface-soft);
  transition: box-shadow 0.15s;
}

.cluster-item[open] {
  box-shadow: var(--shadow-sm);
}

.cluster-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  cursor: pointer;
  user-select: none;
  font-size: 14px;
}

.cluster-summary strong {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-strong);
}

.badge {
  display: inline-flex;
  min-width: 64px;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  background: var(--info-soft, #e0f2fe);
  color: #6b7280;
  border: 1px solid #b2ddff;
}

.member-keys {
  margin: 0;
  padding: 0 16px 12px;
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.member-keys li {
  margin: 0;
}

.member-keys code {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
  background: #f2f4f7;
  padding: 2px 6px;
  border-radius: 4px;
  color: #344054;
}

.skeleton {
  min-height: 120px;
}
</style>
