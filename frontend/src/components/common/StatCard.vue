<template>
  <div class="card">
    <div class="card-title">{{ title }}</div>
    <template v-for="item in items" :key="item.key">
      <div v-if="item.show !== false" :class="['stat-row', { confirmed: item.confirmed }]">
        <span class="stat-k" :title="item.hint">{{ item.label }}</span>
        <template v-if="item.tag">
          <el-tag size="small" :type="item.tag.type">{{ item.tag.text }}</el-tag>
          <span v-if="item.note" class="trunc-reason">{{ item.note }}</span>
        </template>
        <span v-else class="stat-v">{{ item.value }}{{ item.suffix ?? "" }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
export type StatTagType = "success" | "warning" | "danger" | "info";

export interface StatCardItem {
  key: string;
  label: string;
  /** stat-k 悬浮提示 */
  hint?: string;
  /** 绿色强调行（如「已确认」） */
  confirmed?: boolean;
  /** false 时整行不渲染 */
  show?: boolean;
  /** 纯文本值；与 tag 二选一 */
  value?: string | number;
  /** 值后缀，如 % */
  suffix?: string;
  /** 渲染为 el-tag；与 value 二选一 */
  tag?: { type: StatTagType; text: string };
  /** 标签后的附加说明文字（如截断原因） */
  note?: string;
}

export interface StatCardConfig {
  title: string;
  items: StatCardItem[];
}

defineProps<{
  title: string;
  items: StatCardItem[];
}>();
</script>

<style scoped>
.card {
  background: var(--surface-glass-strong, #ffffff);
  border: 1px solid var(--line-soft, #e5e7eb);
  border-radius: var(--radius-md);
  padding: 16px 18px;
  box-shadow: var(--shadow-xs);
}

.card-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-strong);
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--line-soft, #e5e7eb);
}

.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 3px 0;
  font-size: 13px;
}

.stat-k {
  color: var(--text-faint);
}

.stat-v {
  font-weight: 600;
  color: var(--text-strong);
}

.stat-row.confirmed .stat-v {
  color: #059669;
}

.trunc-reason {
  font-size: 12px;
  color: var(--text-faint);
  margin-left: 8px;
}
</style>
