// 命令式 API（ElMessage / ElMessageBox / ElLoading 等）样式集中引入。
// 模板里的 <el-xxx> 组件由 unplugin-vue-components 自动按需注入 CSS。
import "element-plus/theme-chalk/el-message.css";
import "element-plus/theme-chalk/el-message-box.css";
import "element-plus/theme-chalk/el-overlay.css";
import "element-plus/theme-chalk/el-loading.css";
import "element-plus/theme-chalk/el-notification.css";

import "./styles.css";

import { createApp } from "vue";
import { ElLoading, ElNotification } from "element-plus";

import App from "./App.vue";
import { postFrontendEvent } from "./api/diagnostics";

// ── 全局未捕获错误处理 ──────────────────────────────────────────

const ERROR_NOTIFICATION_DURATION = 5000;
const REPORT_DEDUP_WINDOW_MS = 15_000;
const recentReports = new Map<string, number>();

function shouldReport(key: string): boolean {
  const now = Date.now();
  const last = recentReports.get(key) ?? 0;
  if (now - last < REPORT_DEDUP_WINDOW_MS) return false;
  recentReports.set(key, now);
  // 防止 map 无限增长
  if (recentReports.size > 64) {
    const oldest = [...recentReports.entries()].sort((a, b) => a[1] - b[1])[0];
    if (oldest) recentReports.delete(oldest[0]);
  }
  return true;
}

function extractErrorParts(error: unknown): { message: string; stack?: string; type?: string } {
  if (error instanceof Error) {
    return { message: error.message || error.name, stack: error.stack, type: error.name };
  }
  if (typeof error === "string") return { message: error };
  try {
    return { message: JSON.stringify(error) };
  } catch {
    return { message: String(error) };
  }
}

function reportToBackend(prefix: string, error?: unknown): void {
  const parts = extractErrorParts(error);
  const key = `${prefix}|${parts.type ?? ""}|${parts.message}`;
  if (!shouldReport(key)) return;
  // fire-and-forget：失败静默，避免递归触发 errorHandler
  void postFrontendEvent({
    message: parts.message.slice(0, 2000),
    level: "ERROR",
    errorType: parts.type,
    errorStack: parts.stack?.slice(0, 8000),
    module: prefix,
    url: typeof window !== "undefined" ? window.location.href : undefined,
    userAgent: typeof navigator !== "undefined" ? navigator.userAgent : undefined,
    timestamp: new Date().toISOString(),
  }).catch(() => {
    /* ignore */
  });
}

/** 全局错误统一处理：记录日志 + 生产环境弹窗提示用户 + 上报诊断中心。 */
function reportGlobalError(
  consolePrefix: string,
  title: string,
  message: string,
  error?: unknown,
): void {
  console.error(consolePrefix, error);
  reportToBackend(consolePrefix, error);
  // 开发环境避免重复弹窗污染调试体验
  if (import.meta.env.DEV) return;
  ElNotification.error({ title, message, duration: ERROR_NOTIFICATION_DURATION });
}

window.onerror = (_message, _source, _lineno, _colno, error) => {
  reportGlobalError(
    "[window.onerror]",
    "运行时错误",
    "发生未知脚本错误，请刷新页面后重试。",
    error,
  );
};

window.addEventListener("unhandledrejection", (event) => {
  reportGlobalError(
    "[unhandledrejection]",
    "未处理的 Promise 拒绝",
    "请求处理异常，请稍后重试。",
    event.reason,
  );
});

// ── 应用启动 ────────────────────────────────────────────────────

const app = createApp(App);

app.config.errorHandler = (err, _instance, info) => {
  reportGlobalError(
    `[Vue errorHandler] ${info}`,
    "页面渲染异常",
    "页面渲染异常，请刷新页面后重试。",
    err,
  );
};

// 模板使用的 v-loading 指令需要显式注册，不再依赖 use(ElementPlus) 全量注册
app.directive("loading", ElLoading.directive);

app.mount("#app");
