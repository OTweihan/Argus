<template>
  <div class="render-cap-hint">
    已加载 {{ loaded }} 条，为保持流畅仅渲染前 {{ rendered }} 条；可按需过滤或缩小分析范围
  </div>
</template>

<script setup lang="ts">
/** 大列表触顶提示：配合 useRenderCap 使用，替代继续追加的无限滚动入口。 */
defineProps<{
  /** 已加载（参与过滤/统计）的总条数 */
  loaded: number;
  /** 实际渲染的条数 */
  rendered: number;
}>();
</script>

<style scoped>
.render-cap-hint {
  display: block;
  padding: 10px 12px;
  margin: 8px auto 12px;
  border: 1px dashed var(--line-soft, #e4e7ed);
  border-radius: var(--radius-xs, 6px);
  background: rgba(255, 255, 255, 0.55);
  color: var(--text-faint, #6b7280);
  font-size: 12px;
  text-align: center;
}
</style>
