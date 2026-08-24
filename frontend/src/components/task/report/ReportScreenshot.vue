<template>
  <ExtrasSection :label="label">
    <p class="screenshot-path">截图：<code>{{ path }}</code></p>
    <AuthenticatedImage
      class="screenshot"
      :path="resolvedPath"
      :alt="alt"
      @click="$emit('open-lightbox', path)"
    />
  </ExtrasSection>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { screenshotPath as resolveScreenshotPath } from "../../../api";
import AuthenticatedImage from "../../AuthenticatedImage.vue";
import ExtrasSection from "./ExtrasSection.vue";

const props = defineProps<{
  taskId: string;
  path: string;
  alt: string;
  label: string;
}>();

defineEmits<{
  (e: "open-lightbox", path: string): void;
}>();

const resolvedPath = computed(() => resolveScreenshotPath(props.taskId, props.path));
</script>

<style scoped>
.screenshot-path {
  margin: 12px 0;
  color: var(--rp-muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.screenshot-path code {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
  background: #f2f4f7;
  padding: 2px 6px;
  border: 1px solid var(--rp-line);
  border-radius: 7px;
  color: #344054;
}

.screenshot {
  display: block;
  width: 100%;
  max-height: 520px;
  object-fit: contain;
  border-radius: var(--radius-md);
  border: 1px solid var(--rp-line);
  box-shadow: var(--shadow-sm);
  cursor: zoom-in;
  transition: box-shadow var(--transition);
}

.screenshot:hover {
  box-shadow: var(--shadow-md);
}
</style>
