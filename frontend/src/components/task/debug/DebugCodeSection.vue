<template>
  <div v-if="content" class="dbg-section">
    <div class="dbg-section-head" @click="open = !open">
      <span class="dbg-section-title">
        <svg :class="['dbg-sec-chevron', { open }]" viewBox="0 0 16 16" fill="none" width="11" height="11">
          <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
        {{ title }}
      </span>
      <button class="dbg-section-copy" @click.stop="$emit('copy', content)">复制</button>
    </div>
    <div v-if="open" class="dbg-section-body">
      <pre class="dbg-code">{{ content }}</pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";

const props = withDefaults(
    defineProps<{
        title: string;
        content: string;
        defaultOpen?: boolean;
    }>(),
    { defaultOpen: true },
);

defineEmits<{
  (e: "copy", text: string): void;
}>();

const open = ref(props.defaultOpen);
</script>

<style scoped>
.dbg-section {
  border: 1px solid #e6edf0;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 3px rgba(24, 40, 50, 0.04);
}

.dbg-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 9px 14px;
  background: #fafcfc;
  border-bottom: 1px solid #e6edf0;
  cursor: pointer;
  user-select: none;
  transition: background 0.12s ease;
}

.dbg-section-head:hover {
  background: #f0f4f7;
}

.dbg-section-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #1a2a32;
}

.dbg-sec-chevron {
  transition: transform 0.2s ease;
}

.dbg-sec-chevron.open {
  transform: rotate(90deg);
}

.dbg-section-copy {
  padding: 3px 10px;
  border: 1px solid #e6edf0;
  border-radius: 5px;
  background: #fff;
  color: #687a85;
  font-size: 11px;
  font-weight: 540;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.12s ease;
}

.dbg-section-copy:hover {
  background: #f0f4f7;
  color: #1a2a32;
  border-color: #d0dbdf;
}

.dbg-section-body {
  animation: fadeIn 0.18s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.dbg-code {
  margin: 0;
  padding: 14px;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow: auto;
  background: #1a2a32;
  color: #dce8eb;
}
</style>
