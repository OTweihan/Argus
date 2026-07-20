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
const isDev = import.meta.env.DEV;

window.onerror = (_message, _source, _lineno, _colno, error) => {
  console.error("[window.onerror]", error);
  if (isDev) return; // 开发环境保持控制台原生行为
  ElNotification.error({
    title: "运行时错误",
    message: "发生未知脚本错误，请刷新页面后重试。",
    duration: 5000,
  });
};

window.addEventListener("unhandledrejection", (event) => {
  console.error("[unhandledrejection]", event.reason);
  if (isDev) return;
  ElNotification.error({
    title: "未处理的 Promise 拒绝",
    message: "请求处理异常，请稍后重试。",
    duration: 5000,
  });
});

// ── 应用启动 ────────────────────────────────────────────────────

const app = createApp(App);

app.config.errorHandler = (err, _instance, info) => {
  console.error(`[Vue errorHandler] ${info}`, err);
  if (isDev) return;
  ElNotification.error({
    title: "页面渲染异常",
    message: "页面渲染异常，请刷新页面后重试。",
    duration: 5000,
  });
};

// 模板使用的 v-loading 指令需要显式注册，不再依赖 use(ElementPlus) 全量注册
app.directive("loading", ElLoading.directive);

app.mount("#app");
