<template>
  <div class="list-wrap">
    <div class="list-toolbar">
      <el-input
        v-model="classFilter"
        size="small" placeholder="类名..." clearable style="width:220px"
      />
      <el-input
        v-model="methodFilter"
        size="small" placeholder="方法名..." clearable style="width:180px"
      />
      <span v-if="total !== null" class="list-count">共 {{ total }} 个节点</span>
    </div>
    <el-table
      :data="filteredItems"
      size="small" stripe style="width:100%" max-height="400"
      @row-click="toggleNode"
    >
      <el-table-column label="" width="28">
        <template #default="{ row }">
          <span v-if="selectedNodeId === row.callNodeId" class="arrow">▼</span>
          <span v-else class="arrow">▶</span>
        </template>
      </el-table-column>
      <el-table-column label="类名" min-width="200">
        <template #default="{ row }">
          <span class="mono node-name">{{ row.className }}</span>
        </template>
      </el-table-column>
      <el-table-column label="方法" min-width="150">
        <template #default="{ row }">
          <span class="mono">{{ row.methodName }}</span>
        </template>
      </el-table-column>
      <template #append>
        <InfiniteScrollLoad :has-more="hasMore" :loading="loading" @load-more="$emit('load-more')" />
      </template>
    </el-table>

    <!-- Callee edges -->
    <div v-if="selectedNodeId" class="callee-section">
      <div class="callee-header">
        <span class="section-title">被调用方</span>
        <span v-if="calleeLoading" class="callee-hint">加载中...</span>
      </div>
      <el-table :data="calleeItems" size="small" stripe style="width:100%" max-height="300">
        <el-table-column label="方法" min-width="280">
          <template #default="{ row }">
            <span class="mono">{{ row.toClassName || "-" }}.{{ row.toMethodName || "-" }}</span>
          </template>
        </el-table-column>
        <el-table-column label="解析方式" width="100">
          <template #default="{ row }">
            <span class="mono">{{ row.resolutionType }}</span>
          </template>
        </el-table-column>
        <el-table-column label="置信度" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="confidenceTag(row.confidence)">
              {{ row.confidence || "UNKNOWN" }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import type { CallEdgeInfo, CallNodeInfo } from "../../../api/task";
import InfiniteScrollLoad from "../../common/InfiniteScrollLoad.vue";

const props = defineProps<{
  items: CallNodeInfo[];
  total: number | null;
  hasMore: boolean;
  loading: boolean;
  calleeItems: CallEdgeInfo[];
  calleeLoading: boolean;
  selectedNodeId: string | null;
}>();

const emit = defineEmits<{
  "load-more": [];
  "select-node": [callNodeId: string];
}>();

const classFilter = ref("");
const methodFilter = ref("");

const filteredItems = computed(() => {
  const cq = classFilter.value.trim().toLowerCase();
  const mq = methodFilter.value.trim().toLowerCase();
  if (!cq && !mq) return props.items;
  return props.items.filter((n) => {
    if (cq && !n.className.toLowerCase().includes(cq)) return false;
    if (mq && !n.methodName.toLowerCase().includes(mq)) return false;
    return true;
  });
});

function toggleNode(row: CallNodeInfo): void {
  emit("select-node", row.callNodeId);
}

type ElTagType = "success" | "info" | "danger" | "warning" | "primary";

function confidenceTag(c: string | null | undefined): ElTagType {
  if (!c) return "info";
  switch (c.toUpperCase()) {
    case "HIGH": return "success";
    case "MEDIUM": return "warning";
    default: return "info";
  }
}
</script>

<style scoped>
.list-wrap {
  padding: 4px 0;
}

.list-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.list-count {
  font-size: 12px;
  color: var(--text-faint);
}

.arrow {
  font-size: 10px;
  color: var(--text-faint);
  cursor: pointer;
}

.node-name {
  cursor: pointer;
}

.callee-section {
  margin-top: 12px;
  padding: 10px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
}

.callee-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-faint);
}

.callee-hint {
  font-size: 12px;
  color: var(--text-faint);
}

.mono {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}
</style>
