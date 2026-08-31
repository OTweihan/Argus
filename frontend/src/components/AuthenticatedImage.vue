<template>
  <span v-if="loading" class="authenticated-image-placeholder">正在加载图片…</span>
  <span v-else-if="error" class="authenticated-image-error">{{ error }}</span>
  <img
    v-else-if="objectUrl"
    v-bind="$attrs"
    :src="objectUrl"
    :alt="alt"
    :loading="lazy ? 'lazy' : 'eager'"
    @click="$emit('click', $event)"
  />
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { errorMessage } from "../utils";
import { acquireImage, releaseImage } from "./authenticatedImageCache";

defineOptions({ inheritAttrs: false });
defineEmits<{ (event: "click", value: MouseEvent): void }>();

const props = withDefaults(defineProps<{ path: string; alt: string; lazy?: boolean }>(), {
  lazy: true,
});

/* ── 模块级 path→objectUrl 缓存（见 authenticatedImageCache）──
 * 截图组件在展开/收起（v-if 挂载/卸载）时若每次重新下载同一 blob，
 * 会造成大量重复请求。这里按 path 缓存 objectURL，用引用计数跟踪
 * 活跃持有者：归零后不立即 revoke，交由 TTL 惰性回收，使"收起后
 * 再展开"能直接复用缓存而不重复下载。
 */
const objectUrl = ref("");
const loading = ref(false);
const error = ref("");
let generation = 0;
let currentPath = "";
let activeRequest: AbortController | null = null;

watch(
  () => props.path,
  async (path) => {
    const current = ++generation;
    activeRequest?.abort();
    activeRequest = null;
    releaseImage(currentPath);
    currentPath = path;
    error.value = "";
    if (!path) {
      // 路径清空时不能残留旧图（防御性；实际挂载均由 v-if 守卫保证 path 非空）
      objectUrl.value = "";
      return;
    }
    const requestController = new AbortController();
    activeRequest = requestController;
    loading.value = true;
    try {
      const next = await acquireImage(path, requestController.signal);
      if (current !== generation) {
        // 等待期间路径已切换：归还刚取得的持有，交由新路径的持有者接管。
        releaseImage(path);
      } else {
        objectUrl.value = next;
      }
    } catch (caught) {
      if (current === generation) error.value = errorMessage(caught);
    } finally {
      if (activeRequest === requestController) activeRequest = null;
      if (current === generation) loading.value = false;
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  generation += 1;
  activeRequest?.abort();
  activeRequest = null;
  releaseImage(currentPath);
  currentPath = "";
  objectUrl.value = "";
});
</script>

<style scoped>
.authenticated-image-placeholder,
.authenticated-image-error {
  display: block;
  padding: 16px;
  color: var(--text-faint, #6b7280);
  text-align: center;
}

.authenticated-image-error {
  color: var(--danger, #b42318);
}
</style>
