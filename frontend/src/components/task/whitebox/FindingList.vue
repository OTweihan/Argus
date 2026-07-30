<template>
  <div class="finding-list">
    <div class="list-header">
      <span v-if="total !== null" class="total">
        共 {{ total }} 个发现项
      </span>
    </div>

    <div v-if="loading && !items.length" v-loading="loading" class="skeleton" />

    <template v-if="items.length">
      <article
        v-for="f in items"
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

    <div v-if="hasMore" class="load-more">
      <el-button :loading="loading" @click="$emit('load-more')">
        加载更多
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { FindingInfo } from "../../../api/task";

defineProps<{
  items: FindingInfo[];
  total: number | null;
  hasMore: boolean;
  loading: boolean;
}>();

defineEmits<{
  (e: "load-more"): void;
}>();
</script>

<style scoped>
.finding-list {
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

.finding-item {
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 10px;
  background: var(--surface-soft);
  transition: box-shadow 0.15s;
}

.finding-item:hover {
  box-shadow: var(--shadow-sm);
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

.tag-critical { background: var(--danger-soft, #fee2e2); color: #991b1b; border: 1px solid #fecdd3; }
.tag-high { background: var(--danger-soft, #fee2e2); color: #c2410c; border: 1px solid #fecdd3; }
.tag-medium { background: var(--warning-soft, #fef3c7); color: #b45309; border: 1px solid #fedf89; }
.tag-low { background: var(--accent-soft, #e0e7ff); color: #2563eb; border: 1px solid #c7d2fe; }
.tag-info { background: var(--info-soft, #e0f2fe); color: #6b7280; border: 1px solid #b2ddff; }

.finding-meta {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.5);
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
  background: #f2f4f7;
  padding: 1px 6px;
  border-radius: 4px;
  color: #344054;
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

.load-more {
  display: flex;
  justify-content: center;
  margin-top: 12px;
}

.skeleton {
  min-height: 120px;
}
</style>
