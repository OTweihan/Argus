// 命令式 API（ElMessage / ElMessageBox / ElLoading 等）样式集中引入。
// 模板里的 <el-xxx> 组件由 unplugin-vue-components 自动按需注入 CSS。
import "element-plus/theme-chalk/el-message.css";
import "element-plus/theme-chalk/el-message-box.css";
import "element-plus/theme-chalk/el-overlay.css";
import "element-plus/theme-chalk/el-loading.css";

import "./styles.css";

import { createApp } from "vue";
import { ElLoading, ElNotification } from "element-plus";

import App from "./App.vue";

// ── 全局未捕获错误处理 ──────────────────────────────────────────

const ERROR_NOTIFICATION_DURATION = 5000;

/** 全局错误统一处理：记录日志 + 生产环境弹窗提示用户。 */
function reportGlobalError(
  consolePrefix: string,
  title: string,
  message: string,
  error?: unknown,
): void {
  console.error(consolePrefix, error);
  // 开发环境避免重复弹窗污染调试体验
  if (import.meta.env.DEV) return;
  ElNotification.error({ title, message, duration: ERROR_NOTIFICATION_DURATION });
}

window.onerror = (_message, _source, _lineno, _colno, error) => {
  reportGlobalError("[window.onerror]", "运行时错误", "发生未知脚本错误，请刷新页面后重试。", error);
};

window.addEventListener("unhandledrejection", (event) => {
  reportGlobalError("[unhandledrejection]", "未处理的 Promise 拒绝", "请求处理异常，请稍后重试。", event.reason);
});

// ── 应用启动 ────────────────────────────────────────────────────

const app = createApp(App);

app.config.errorHandler = (err, _instance, info) => {
  reportGlobalError(`[Vue errorHandler] ${info}`, "页面渲染异常", "页面渲染异常，请刷新页面后重试。", err);
};

// 模板使用的 v-loading 指令需要显式注册，不再依赖 use(ElementPlus) 全量注册
app.directive("loading", ElLoading.directive);

app.mount("#app");
