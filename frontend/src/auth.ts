import { computed, ref } from "vue";

const SESSION_TOKEN_KEY = "argus.apiToken";

function readSessionToken(): string {
  try {
    return window.sessionStorage.getItem(SESSION_TOKEN_KEY)?.trim() ?? "";
  } catch {
    return "";
  }
}

const apiToken = ref(readSessionToken());
export const authRequired = ref(false);
export const hasApiToken = computed(() => apiToken.value.length > 0);

export function getApiToken(): string {
  return apiToken.value;
}

export function setApiToken(token: string): void {
  const normalized = token.trim();
  apiToken.value = normalized;
  authRequired.value = false;
  try {
    if (normalized) window.sessionStorage.setItem(SESSION_TOKEN_KEY, normalized);
    else window.sessionStorage.removeItem(SESSION_TOKEN_KEY);
  } catch {
    // 隐私模式可能禁用 sessionStorage；内存中的 token 仍可用于当前页面。
  }
}

export function clearApiToken(): void {
  setApiToken("");
}

export function requireApiToken(): void {
  authRequired.value = true;
}
