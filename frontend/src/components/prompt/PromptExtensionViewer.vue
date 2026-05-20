<template>
  <div v-if="hasContent" class="prompt-extension-viewer">
    <div v-for="role in ROLES" :key="role.value" class="ext-block">
      <div class="ext-title">
        {{ role.label }}
      </div>
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div v-if="rendered[role.value]" class="md-body" v-html="rendered[role.value]" />
      <div v-else class="md-body empty">
        未配置
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import {computed} from "vue";

import {renderMarkdown} from "../../composables/useMarkdown";
import {hasAnyExtension, type PromptExtensions} from "../../promptExtensions";

const props = defineProps<{ extensions: PromptExtensions }>();

const ROLES = [
  {value: "planner" as const, label: "Planner 扩展"},
  {value: "evaluator" as const, label: "Evaluator 扩展"},
];

const hasContent = computed(() => hasAnyExtension(props.extensions));

const rendered = computed(() => ({
  planner: renderMarkdown(props.extensions.planner),
  evaluator: renderMarkdown(props.extensions.evaluator),
}));
</script>

<style scoped>
.prompt-extension-viewer {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ext-block {
  border: 1px solid var(--line-soft, #e4e7ed);
  border-radius: var(--radius-sm, 8px);
  background: var(--surface-soft, #fafbff);
  overflow: hidden;
}

.ext-title {
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-faint, #6b7280);
  background: rgba(99, 102, 241, 0.05);
  border-bottom: 1px solid var(--line-soft, #e4e7ed);
}

.md-body {
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-strong, #11181c);
  word-break: break-word;
}

.md-body.empty {
  color: var(--text-faint, #9aa1ad);
}

.md-body :deep(p) {
  margin: 0 0 8px;
}

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 0 0 8px;
  padding-left: 20px;
}

.md-body :deep(code) {
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(99, 102, 241, 0.08);
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}

.md-body :deep(pre) {
  margin: 0 0 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.04);
  overflow-x: auto;
}
</style>
