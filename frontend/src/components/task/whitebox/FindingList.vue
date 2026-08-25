<template>
  <div class="finding-list">
    <div class="list-header">
      <span v-if="total !== null" class="total"> 共 {{ total }} 个发现项 </span>
      <span class="sort-indicator" aria-label="按严重程度从高到低排序">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M5 3v10m0 0-2.5-2.5M5 13l2.5-2.5M10 4h3M10 8h2M10 12h1" />
        </svg>
        严重程度：高 → 中 → 低
      </span>
    </div>

    <div v-if="loading && !items.length" v-loading="loading" class="skeleton" />

    <template v-if="items.length">
      <article
        v-for="f in visibleItems"
        :key="f.findingId"
        :class="['finding-item', 'sev-' + f.severity.toLowerCase()]"
      >
        <div class="finding-head">
          <div class="title-row">
            <h4>{{ f.title }}</h4>
            <span :class="['severity-tag', 'tag-' + f.severity.toLowerCase()]">
              {{ f.severity }}
            </span>
          </div>
          <p class="desc">
            {{ f.description }}
          </p>
        </div>

        <div class="finding-meta">
          <div class="meta-item">
            <span class="meta-label">规则 ID</span>
            <code>{{ f.ruleId || "-" }}</code>
          </div>
          <div class="meta-item">
            <span class="meta-label">规则类别</span>
            <span>{{ f.ruleCategory || "-" }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">置信度</span>
            <span>{{ f.confidence || "-" }}</span>
          </div>
          <div v-if="f.location" class="meta-item full-width">
            <span class="meta-label">位置</span>
            <code>{{ f.location }}</code>
          </div>
          <div v-if="f.snippet" class="meta-item full-width">
            <span class="meta-label">代码片段</span>
            <pre class="snippet"><code>{{ f.snippet }}</code></pre>
          </div>
        </div>
      </article>
    </template>

    <el-empty v-else-if="!loading" description="该分析执行未产生发现项" />

    <RenderCapHint
      v-if="hiddenCount > 0"
      :loaded="sortedItems.length"
      :rendered="visibleItems.length"
    />
    <InfiniteScrollLoad
      v-else
      :has-more="hasMore"
      :loading="loading"
      @load-more="$emit('load-more')"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { FindingInfo } from "../../../api/task";
import { useRenderCap } from "../../../composables/useRenderCap";
import InfiniteScrollLoad from "../../common/InfiniteScrollLoad.vue";
import RenderCapHint from "../../common/RenderCapHint.vue";
import { severityRank } from "./severity";

const props = defineProps<{
  items: FindingInfo[];
  total: number | null;
  hasMore: boolean;
  loading: boolean;
}>();

defineEmits<{
  (e: "load-more"): void;
}>();

const sortedItems = computed(() =>
  [...props.items].sort(
    (left, right) => severityRank(left.severity) - severityRank(right.severity),
  ),
);

// 渲染上限：排序在全量已加载数据上进行（触顶时优先展示严重程度最高的条目），
// 仅 DOM 渲染截断。
const { visibleItems, hiddenCount } = useRenderCap(sortedItems);
</script>

<style scoped>
.finding-list {
  padding: 2px 0;
}

.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.total {
  font-size: 13px;
  color: var(--text-faint);
}

.sort-indicator {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 9px;
  border: 1px solid var(--brand-200);
  border-radius: var(--radius-pill);
  color: var(--brand-700);
  background: var(--brand-50);
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.sort-indicator svg {
  width: 13px;
  height: 13px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.finding-item {
  border: 1px solid var(--line-soft);
  border-left-width: 4px;
  border-radius: var(--radius-md);
  padding: 16px 18px;
  margin-bottom: 12px;
  background: var(--surface-glass-strong);
  transition:
    transform var(--transition-fast),
    box-shadow var(--transition-fast);
}

.finding-item:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

.finding-item.sev-critical {
  border-left-color: #991b1b;
}
.finding-item.sev-high {
  border-left-color: #c2410c;
}
.finding-item.sev-medium {
  border-left-color: #b45309;
}
.finding-item.sev-low {
  border-left-color: #2563eb;
}
.finding-item.sev-info {
  border-left-color: #64748b;
}

.finding-head {
  margin-bottom: 10px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.title-row h4 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}

.desc {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}

.severity-tag {
  display: inline-flex;
  align-items: center;
  min-width: 64px;
  justify-content: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.tag-critical {
  background: var(--danger-soft, #fee2e2);
  color: #991b1b;
  border: 1px solid #fecdd3;
}
.tag-high {
  background: var(--danger-soft, #fee2e2);
  color: #c2410c;
  border: 1px solid #fecdd3;
}
.tag-medium {
  background: var(--warning-soft, #fef3c7);
  color: #b45309;
  border: 1px solid #fedf89;
}
.tag-low {
  background: var(--accent-soft, #e0e7ff);
  color: #2563eb;
  border: 1px solid #c7d2fe;
}
.tag-info {
  background: var(--info-soft, #e0f2fe);
  color: #6b7280;
  border: 1px solid #b2ddff;
}

.finding-meta {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--surface-soft);
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line-soft);
}

.meta-item.full-width {
  grid-column: 1 / -1;
}

.meta-item:last-child {
  border-bottom: 0;
}

.meta-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-faint);
}

.meta-item span:not(.meta-label),
.meta-item code {
  font-size: 13px;
  color: var(--text-strong);
  overflow-wrap: anywhere;
}

code {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
  background: #edf8f7;
  padding: 1px 6px;
  border-radius: 4px;
  color: #245c59;
}

.snippet {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 120px;
  overflow-y: auto;
}

.snippet code {
  display: block;
  font-size: 12px;
}

.skeleton {
  min-height: 120px;
}

@media (max-width: 720px) {
  .list-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .finding-meta {
    grid-template-columns: 1fr;
  }

  .meta-item.full-width {
    grid-column: auto;
  }

  .title-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
