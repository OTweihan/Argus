<template>
  <div v-if="hasMore || loading" ref="root" class="inf-load">
    <span v-if="loading" class="inf-spinner" />
    <span v-if="loading" class="inf-text">加载中...</span>
    <span v-else class="inf-text">下滑加载更多</span>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{
  hasMore: boolean;
  loading: boolean;
}>();

const emit = defineEmits<{ "load-more": [] }>();

const root = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;

function observe(): void {
  observer?.disconnect();
  observer = null;
  if (typeof IntersectionObserver === "undefined") return;
  if (!props.hasMore || props.loading) return;
  if (!root.value) return;
  observer = new IntersectionObserver((entries) => {
    if (entries[0]?.isIntersecting && props.hasMore && !props.loading) {
      emit("load-more");
    }
  });
  observer.observe(root.value);
}

onMounted(observe);

// 加载完成后且仍有更多时，重新观察以便继续触底加载。
// flush: "post" 确保 v-if 渲染的哨兵节点已在 DOM 中后再观察，避免拿到旧节点。
watch([() => props.hasMore, () => props.loading], observe, { flush: "post" });

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
});
</script>

<style scoped>
.inf-load {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 32px;
  width: 100%;
  font-size: 12px;
  color: var(--text-faint, #9ca3af);
}

.inf-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--line-strong, #c7d2fe);
  border-top-color: var(--brand-600, #079994);
  border-radius: 50%;
  animation: inf-spin 0.7s linear infinite;
}

.inf-text {
  letter-spacing: 0.02em;
}

@keyframes inf-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
