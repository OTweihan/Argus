<template>
  <div class="extras">
    <button type="button" class="extras-toggle" @click="open = !open">
      <svg
        :class="['chevron', { open }]"
        viewBox="0 0 16 16"
        fill="none"
        width="12"
        height="12"
      >
        <path
          d="M6 4l4 4-4 4"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linecap="round"
        />
      </svg>
      {{ label }}
    </button>
    <div v-if="open" class="extras-content">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";

defineProps<{
  label: string;
}>();

const open = ref(false);
</script>

<style scoped>
.extras {
  margin-top: 2px;
  width: 100%;
}

.extras-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--rp-line);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.6);
  color: var(--rp-muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition);
  font-family: inherit;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.extras-toggle:hover {
  background: var(--accent-soft);
  color: var(--accent);
  border-color: var(--brand-200);
  box-shadow: 0 4px 12px rgba(10, 186, 181, 0.12);
}

.chevron {
  transition: transform var(--transition);
}

.chevron.open {
  transform: rotate(90deg);
}

.extras-content {
  width: 100%;
  margin-top: 10px;
  animation: fadeIn 0.2s ease;
}
</style>
