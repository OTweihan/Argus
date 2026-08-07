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
import { loadObjectUrl } from "../api";
import { errorMessage } from "../utils";

defineOptions({ inheritAttrs: false });
defineEmits<{ (event: "click", value: MouseEvent): void }>();

const props = withDefaults(defineProps<{ path: string; alt: string; lazy?: boolean }>(), {
  lazy: true,
});

/* ── 模块级 path→objectUrl 缓存 ─────────────────────────────
 * 截图组件在展开/收起（v-if 挂载/卸载）时若每次重新下载同一 blob，
 * 会造成大量重复请求。这里按 path 缓存 objectURL，用引用计数跟踪
 * 活跃持有者：归零后不立即 revoke，交由 TTL 惰性回收，使"收起后
 * 再展开"能直接复用缓存而不重复下载。
 */
interface ImageCacheEntry {
  url: string;
  refCount: number;
  lastUsed: number;
}
const imageCache = new Map<string, ImageCacheEntry>();
const pendingFetches = new Map<string, Promise<string>>();
const CACHE_TTL_MS = 120_000;

function evictStale(): void {
  const now = Date.now();
  for (const [path, entry] of imageCache) {
    if (entry.refCount === 0 && now - entry.lastUsed > CACHE_TTL_MS) {
      imageCache.delete(path);
      URL.revokeObjectURL(entry.url);
    }
  }
}

/** 为组件取得一次对 path 的持有；命中缓存直接复用，否则发起（同 path 去重）拉取。 */
async function acquireImage(path: string): Promise<string> {
  const cached = imageCache.get(path);
  if (cached) {
    cached.refCount += 1;
    cached.lastUsed = Date.now();
    return cached.url;
  }
  let pending = pendingFetches.get(path);
  if (!pending) {
    pending = loadObjectUrl(path);
    pendingFetches.set(path, pending);
  }
  try {
    const url = await pending;
    const entry = imageCache.get(path);
    if (entry) {
      entry.refCount += 1;
      entry.lastUsed = Date.now();
      return entry.url;
    }
    imageCache.set(path, { url, refCount: 1, lastUsed: Date.now() });
    evictStale();
    return url;
  } finally {
    pendingFetches.delete(path);
  }
}

/** 归还一次持有；归零后交由 TTL 惰性回收，不立即 revoke。 */
function releaseImage(path: string): void {
  const entry = imageCache.get(path);
  if (!entry) return;
  entry.refCount = Math.max(0, entry.refCount - 1);
  entry.lastUsed = Date.now();
}

const objectUrl = ref("");
const loading = ref(false);
const error = ref("");
let generation = 0;
let currentPath = "";

watch(
  () => props.path,
  async (path) => {
    const current = ++generation;
    releaseImage(currentPath);
    currentPath = path;
    error.value = "";
    if (!path) {
      // 路径清空时不能残留旧图（防御性；实际挂载均由 v-if 守卫保证 path 非空）
      objectUrl.value = "";
      return;
    }
    loading.value = true;
    try {
      const next = await acquireImage(path);
      if (current !== generation) {
        // 等待期间路径已切换：归还刚取得的持有，交由新路径的持有者接管。
        releaseImage(path);
      } else {
        objectUrl.value = next;
      }
    } catch (caught) {
      if (current === generation) error.value = errorMessage(caught);
    } finally {
      if (current === generation) loading.value = false;
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  generation += 1;
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
