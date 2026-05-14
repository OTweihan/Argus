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
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-md, 14px);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: var(--shadow-sm, 0 4px 12px rgba(15, 23, 42, 0.05));
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  overflow: hidden;
  transition: box-shadow var(--transition-base, 0.22s cubic-bezier(0.4, 0, 0.2, 1));
}

.dbg-section:hover {
  box-shadow: var(--shadow-md, 0 12px 28px rgba(15, 23, 42, 0.07));
}

.dbg-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 11px 14px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.65) 0%, rgba(248, 250, 252, 0.45) 100%);
  border-bottom: 1px solid var(--line-soft, #e4e7ed);
  cursor: pointer;
  user-select: none;
  transition: background var(--transition-fast, 0.15s cubic-bezier(0.4, 0, 0.2, 1));
}

.dbg-section-head:hover {
  background: linear-gradient(180deg, rgba(244, 243, 255, 0.7) 0%, rgba(248, 250, 252, 0.5) 100%);
}

.dbg-section-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-strong, #11181c);
}

.dbg-sec-chevron {
  transition: transform var(--transition-fast, 0.15s cubic-bezier(0.4, 0, 0.2, 1));
  color: var(--brand-600, #4f46e5);
}

.dbg-sec-chevron.open {
  transform: rotate(90deg);
}

.dbg-section-copy {
  padding: 4px 12px;
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-xs, 6px);
  background: rgba(255, 255, 255, 0.7);
  color: var(--text-faint, #6b7280);
  font-size: 11px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all var(--transition-fast, 0.15s cubic-bezier(0.4, 0, 0.2, 1));
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.dbg-section-copy:hover {
  background: var(--brand-50, #f4f3ff);
  color: var(--brand-600, #4f46e5);
  border-color: var(--brand-100, #e0e7ff);
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.12);
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
  background: #0f172a;
  color: #e2e8f0;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
}
</style>
