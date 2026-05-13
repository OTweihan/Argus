// 命令式 API（ElMessage / ElMessageBox / ElLoading 等）样式集中引入。
// 模板里的 <el-xxx> 组件由 unplugin-vue-components 自动按需注入 CSS。
import "element-plus/theme-chalk/el-message.css";
import "element-plus/theme-chalk/el-message-box.css";
import "element-plus/theme-chalk/el-overlay.css";
import "element-plus/theme-chalk/el-loading.css";

import "./styles.css";

import { createApp } from "vue";
import { ElLoading } from "element-plus";

import App from "./App.vue";

const app = createApp(App);

// 模板使用的 v-loading 指令需要显式注册，不再依赖 use(ElementPlus) 全量注册
app.directive("loading", ElLoading.directive);

app.mount("#app");
