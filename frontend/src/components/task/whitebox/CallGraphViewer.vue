<template>
  <div class="list-wrap">
    <div class="list-toolbar">
      <el-input v-model="classFilter" class="class-filter" placeholder="类名" clearable />
      <el-input v-model="methodFilter" class="method-filter" placeholder="方法名" clearable />
      <span v-if="total !== null" class="list-count">共 {{ total }} 个节点</span>
    </div>
    <el-table
      :data="visibleItems"
      row-key="callNodeId"
      :expand-row-keys="expandedRowKeys"
      size="small"
      stripe
      style="width: 100%"
      @row-click="toggleNode"
      @expand-change="toggleExpandedNode"
    >
      <el-table-column type="expand" width="44">
        <template #default="{ row }">
          <div v-if="selectedNodeId === row.callNodeId" class="callee-section" @click.stop>
            <div class="callee-header">
              <span class="callee-heading-icon" aria-hidden="true">
                <svg viewBox="0 0 20 20" fill="none">
                  <circle cx="5" cy="10" r="2.25" stroke="currentColor" stroke-width="1.5" />
                  <circle cx="15" cy="5" r="2.25" stroke="currentColor" stroke-width="1.5" />
                  <circle cx="15" cy="15" r="2.25" stroke="currentColor" stroke-width="1.5" />
                  <path
                    d="M7.2 9.2l5.55-3.1M7.2 10.8l5.55 3.1"
                    stroke="currentColor"
                    stroke-width="1.3"
                  />
                </svg>
              </span>
              <span class="callee-heading-copy">
                <strong class="section-title">下游调用</strong>
                <span class="callee-source mono">{{ row.className }}.{{ row.methodName }}</span>
              </span>
              <span v-if="!calleeLoading" class="callee-count">{{ calleeItems.length }} 条</span>
            </div>

            <div v-if="calleeLoading" class="callee-loading-state">
              <span class="callee-spinner" />
              <span>正在解析下游调用...</span>
            </div>
            <div v-else-if="calleeItems.length" class="callee-list">
              <article v-for="edge in calleeItems" :key="edge.callEdgeId" class="callee-item">
                <span class="edge-icon" aria-hidden="true">
                  <svg viewBox="0 0 16 16" fill="none">
                    <path
                      d="M3 8h9M9 5l3 3-3 3"
                      stroke="currentColor"
                      stroke-width="1.5"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                </span>
                <div class="edge-target">
                  <span class="edge-class mono">{{ edge.toClassName || "未解析类" }}</span>
                  <strong class="edge-method mono">{{ edge.toMethodName || "未解析方法" }}</strong>
                </div>
                <div class="edge-meta">
                  <span class="resolution-chip" :title="edge.resolutionType">
                    {{ resolutionLabel(edge.resolutionType) }}
                  </span>
                  <el-tag size="small" effect="light" round :type="confidenceTag(edge.confidence)">
                    {{ confidenceLabel(edge.confidence) }}
                  </el-tag>
                </div>
              </article>
            </div>
            <div v-else class="callee-empty">
              <span class="empty-icon">∅</span>
              <span>该节点没有下游调用</span>
            </div>
          </div>
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
        <RenderCapHint
          v-if="hiddenCount > 0"
          :loaded="filteredItems.length"
          :rendered="visibleItems.length"
        />
        <InfiniteScrollLoad
          v-else
          :has-more="hasMore"
          :loading="loading"
          @load-more="$emit('load-more')"
        />
      </template>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { CallEdgeInfo, CallNodeInfo } from "../../../api/task";
import { useDebounceFn } from "../../../composables/useDebounceFn";
import { useRenderCap } from "../../../composables/useRenderCap";
import type { ElTagType } from "../../../utils";
import InfiniteScrollLoad from "../../common/InfiniteScrollLoad.vue";
import RenderCapHint from "../../common/RenderCapHint.vue";

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
const appliedClassFilter = ref("");
const appliedMethodFilter = ref("");
const commitFilters = useDebounceFn((classValue: string, methodValue: string) => {
  appliedClassFilter.value = classValue;
  appliedMethodFilter.value = methodValue;
}, 220);

watch([classFilter, methodFilter], ([classValue, methodValue]) => {
  if (!classValue.trim() && !methodValue.trim()) {
    commitFilters.cancel();
    appliedClassFilter.value = "";
    appliedMethodFilter.value = "";
    return;
  }
  commitFilters(classValue, methodValue);
});

const expandedRowKeys = computed(() => (props.selectedNodeId ? [props.selectedNodeId] : []));

const filteredItems = computed(() => {
  const cq = appliedClassFilter.value.trim().toLowerCase();
  const mq = appliedMethodFilter.value.trim().toLowerCase();
  if (!cq && !mq) return props.items;
  return props.items.filter((n) => {
    if (cq && !n.className.toLowerCase().includes(cq)) return false;
    if (mq && !n.methodName.toLowerCase().includes(mq)) return false;
    return true;
  });
});

// 渲染上限：过滤在全量已加载数据上进行，仅 DOM 渲染截断（触顶提示过滤）。
const { visibleItems, hiddenCount } = useRenderCap(filteredItems);

function toggleNode(row: CallNodeInfo): void {
  emit("select-node", row.callNodeId);
}

function toggleExpandedNode(row: CallNodeInfo): void {
  emit("select-node", row.callNodeId);
}

function confidenceTag(c: string | null | undefined): ElTagType {
  if (!c) return "info";
  switch (c.toUpperCase()) {
    case "HIGH":
      return "success";
    case "MEDIUM":
      return "warning";
    default:
      return "info";
  }
}

function confidenceLabel(c: string | null | undefined): string {
  switch (c?.toUpperCase()) {
    case "HIGH":
      return "高置信度";
    case "MEDIUM":
      return "中置信度";
    case "LOW":
      return "低置信度";
    default:
      return "未知置信度";
  }
}

function resolutionLabel(type: string): string {
  switch (type) {
    case "SYMBOL_SOLVER":
      return "精确解析";
    case "SOURCE_SCOPE_FALLBACK":
      return "作用域推断";
    case "UNRESOLVED":
      return "未解析";
    default:
      return type;
  }
}
</script>

<style scoped>
.list-wrap {
  padding: 2px 0;
}

.list-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.class-filter {
  width: 240px;
}

.method-filter {
  width: 200px;
}

.list-count {
  font-size: 12px;
  color: var(--text-faint);
}

.node-name {
  cursor: pointer;
}

.callee-section {
  padding: 18px 22px 20px 58px;
  border-top: 1px solid rgba(10, 186, 181, 0.18);
  border-bottom: 1px solid rgba(10, 186, 181, 0.16);
  background:
    linear-gradient(90deg, rgba(10, 186, 181, 0.08), transparent 34%), rgba(248, 253, 252, 0.96);
  box-shadow: inset 3px 0 0 var(--brand-500);
}

.list-wrap :deep(.el-table__expanded-cell) {
  padding: 0 !important;
  background: transparent !important;
}

.list-wrap :deep(.el-table__expand-icon) {
  display: inline-grid;
  width: 25px;
  height: 25px;
  place-items: center;
  border: 1px solid var(--brand-100);
  border-radius: 8px;
  color: var(--brand-700);
  background: var(--brand-50);
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast),
    box-shadow var(--transition-fast);
}

.list-wrap :deep(.el-table__expand-icon:hover),
.list-wrap :deep(.el-table__expand-icon--expanded) {
  border-color: var(--brand-200);
  background: var(--brand-100);
  box-shadow: 0 3px 8px rgba(10, 186, 181, 0.16);
}

.list-wrap :deep(.el-table__row.expanded > td.el-table__cell) {
  background: rgba(236, 254, 253, 0.72) !important;
}

.callee-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.callee-heading-icon {
  display: inline-grid;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  place-items: center;
  border: 1px solid var(--brand-100);
  border-radius: 10px;
  color: var(--brand-700);
  background: rgba(255, 255, 255, 0.8);
  box-shadow: var(--shadow-xs);
}

.callee-heading-icon svg {
  width: 20px;
  height: 20px;
}

.callee-heading-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.section-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-strong);
}

.callee-source {
  overflow: hidden;
  color: var(--text-faint);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.callee-count {
  padding: 4px 9px;
  flex: 0 0 auto;
  border: 1px solid var(--brand-100);
  border-radius: var(--radius-pill);
  color: var(--brand-700);
  background: rgba(255, 255, 255, 0.76);
  font-size: 11px;
  font-weight: 700;
}

.callee-list {
  display: grid;
  gap: 8px;
}

.callee-item {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.84);
  box-shadow: var(--shadow-xs);
  transition:
    transform var(--transition-fast),
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.callee-item:hover {
  transform: translateX(2px);
  border-color: rgba(10, 186, 181, 0.28);
  box-shadow: var(--shadow-sm);
}

.edge-icon {
  display: inline-grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 9px;
  color: var(--brand-700);
  background: var(--brand-50);
}

.edge-icon svg {
  width: 16px;
  height: 16px;
}

.edge-target {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.edge-class {
  overflow: hidden;
  color: var(--text-faint);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.edge-method {
  overflow: hidden;
  color: var(--text-strong);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.edge-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.resolution-chip {
  padding: 3px 8px;
  border-radius: var(--radius-pill);
  color: var(--text-muted);
  background: var(--surface-muted);
  font-size: 11px;
  font-weight: 600;
}

.callee-loading-state,
.callee-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  min-height: 72px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius-sm);
  color: var(--text-faint);
  background: rgba(255, 255, 255, 0.5);
  font-size: 12px;
}

.callee-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--brand-100);
  border-top-color: var(--brand-700);
  border-radius: 50%;
  animation: callee-spin 0.7s linear infinite;
}

.empty-icon {
  display: inline-grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 50%;
  color: var(--text-placeholder);
  background: var(--surface-muted);
  font-weight: 700;
}

@keyframes callee-spin {
  to {
    transform: rotate(360deg);
  }
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

  .class-filter,
  .method-filter {
    width: 100%;
  }

  .callee-section {
    padding: 16px 12px 18px;
  }

  .callee-item {
    grid-template-columns: 28px minmax(0, 1fr);
  }

  .edge-meta {
    grid-column: 2;
    flex-wrap: wrap;
  }
}
</style>
