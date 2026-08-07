<template>
  <div class="snippet-wrapper">
    <div class="snippet-header">
      <span class="snippet-path">{{ filePath || "(unknown)" }}</span>
      <button v-if="filePath" class="snippet-copy" @click="copyPath">
        <svg viewBox="0 0 16 16" fill="none" width="14" height="14">
          <rect x="5" y="3" width="9" height="11" rx="1" stroke="currentColor" stroke-width="1.2" />
          <path d="M3 5H2v9a1 1 0 001 1h7" stroke="currentColor" stroke-width="1.2" />
        </svg>
        复制路径
      </button>
    </div>
    <div class="snippet-body" :class="{ collapsed: isCollapsed && !expanded }">
      <div v-for="(line, idx) in displayedLines" :key="idx" class="snippet-line" :class="{ highlight: highlightedSet.has(startLine + idx) }">
        <span class="snippet-ln">{{ startLine + idx }}</span>
        <span class="snippet-text">{{ line }}</span>
      </div>
    </div>
    <button
      v-if="needsCollapse"
      class="snippet-toggle"
      @click="expanded = !expanded"
    >
      {{ expanded ? "收起" : `展开全部（${totalLines} 行）` }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";

const props = withDefaults(defineProps<{
  code: string;
  filePath?: string | null;
  startLine?: number;
  maxLines?: number;
  highlightLines?: number[];
}>(), {
  filePath: null,
  startLine: 1,
  maxLines: 30,
  highlightLines: () => [],
});

const expanded = ref(false);

const lines = computed(() =>
  props.code.split("\n").map((l) =>
    l
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;") || " ",
  ),
);

const totalLines = computed(() => lines.value.length);
const needsCollapse = computed(() => totalLines.value > props.maxLines);
const isCollapsed = computed(() => needsCollapse.value && !expanded.value);
const displayedLines = computed(() =>
  isCollapsed.value
    ? lines.value.slice(0, props.maxLines)
    : lines.value,
);
const highlightedSet = computed(() => new Set(props.highlightLines));

function copyPath(): void {
  if (!props.filePath) return;
  navigator.clipboard.writeText(props.filePath).catch(() => {});
}
</script>

<style scoped>
.snippet-wrapper {
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-sm, 8px);
  overflow: hidden;
  background: #fafbfc;
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 13px;
  margin: 8px 0;
}

.snippet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: #f0f2f5;
  border-bottom: 1px solid var(--line-soft, #e4e7ed);
}

.snippet-path {
  font-size: 12px;
  color: var(--text-faint, #6b7280);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snippet-copy {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--brand-700, #087b78);
  cursor: pointer;
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}

.snippet-copy:hover {
  background: var(--brand-50, #ecfefd);
}

.snippet-body {
  overflow-x: auto;
  transition: max-height 0.15s;
}

.snippet-body.collapsed {
  overflow: hidden;
}

.snippet-line {
  display: flex;
  min-height: 22px;
}

.snippet-line.highlight {
  background: rgba(251, 191, 36, 0.15);
}

.snippet-ln {
  flex: 0 0 48px;
  text-align: right;
  padding: 1px 10px 1px 6px;
  color: var(--text-faint, #9ca3af);
  user-select: none;
  border-right: 1px solid var(--line-soft, #e4e7ed);
}

.snippet-text {
  flex: 1;
  padding: 1px 12px;
  white-space: pre;
  color: var(--text-strong, #11181c);
}

.snippet-toggle {
  display: block;
  width: 100%;
  padding: 6px 0;
  border: none;
  border-top: 1px solid var(--line-soft, #e4e7ed);
  background: #f0f2f5;
  color: var(--brand-700, #087b78);
  cursor: pointer;
  font-size: 12px;
  font-family: inherit;
}

.snippet-toggle:hover {
  background: #e5e7eb;
}
</style>
