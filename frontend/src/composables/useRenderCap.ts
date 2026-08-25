import { computed, toValue, type MaybeRefOrGetter } from "vue";

/** 大列表渲染上限：超过后仅渲染前 limit 条并提示过滤/缩小范围。 */
export const RENDER_CAP = 500;

/**
 * 大列表渲染上限守卫。
 *
 * 无限滚动分页会让 el-table / v-for 列表无限累积 DOM 行数，大型分析下
 * 滚动与过滤输入随之卡顿。本守卫把「已加载数据」与「实际渲染条数」解耦：
 * 数据仍全量参与过滤、排序与统计，但超过 limit 时只渲染前 limit 条，
 * 超出部分经 hiddenCount 提示用户缩小范围。
 *
 * 使用示例：
 *   const { visibleItems, hiddenCount } = useRenderCap(filteredItems);
 */
export function useRenderCap<T>(source: MaybeRefOrGetter<T[]>, limit: number = RENDER_CAP) {
  const visibleItems = computed(() => {
    const base = toValue(source);
    return base.length > limit ? base.slice(0, limit) : base;
  });
  const hiddenCount = computed(() => Math.max(0, toValue(source).length - limit));
  return { visibleItems, hiddenCount };
}
