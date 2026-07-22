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
  >
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

const objectUrl = ref("");
const loading = ref(false);
const error = ref("");
let generation = 0;

function release(): void {
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value);
  objectUrl.value = "";
}

watch(() => props.path, async (path) => {
  const current = ++generation;
  release();
  error.value = "";
  if (!path) return;
  loading.value = true;
  try {
    const next = await loadObjectUrl(path);
    if (current !== generation) URL.revokeObjectURL(next);
    else objectUrl.value = next;
  } catch (caught) {
    if (current === generation) error.value = errorMessage(caught);
  } finally {
    if (current === generation) loading.value = false;
  }
}, { immediate: true });

onBeforeUnmount(() => {
  generation += 1;
  release();
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

.authenticated-image-error { color: var(--danger, #b42318); }
</style>
