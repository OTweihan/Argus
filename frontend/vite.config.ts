import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";

export default defineConfig({
  root: ".",
  base: "/",
  plugins: [
    vue(),
    // 模板里的 <el-xxx> 组件会被 ElementPlusResolver 自动按需 import 并注入 CSS。
    // 命令式 API（ElMessage/ElMessageBox 等）通过显式 import + main.ts 集中引入对应样式处理。
    Components({
      resolvers: [ElementPlusResolver()],
      dts: "src/components.d.ts",
    }),
  ],
  build: {
    outDir: "../argus_py/api/static",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        // 对象形式的 manualChunks 会把 element-plus 当作 entry（addAdditionalModules），
        // 导致其 barrel（es/index.mjs re-export 全部组件）连同整个传递依赖图进入
        // 单一 chunk 且 tree-shaking 被禁用（实测残留 el-carousel 等未用组件）。
        //
        // 实测函数形式同样不要对 element-plus 分组：一旦 element-plus 进入 manual chunk，
        // tree-shaking 即失效，vendor chunk 回到 ~904 KB；交由 Rollup 自动分包后
        // element-plus 被 tree-shake 到 ~190 KB（entry 236 KB/gzip 81 KB），且
        // el-table / el-form / el-tabs 等只在具体视图用到的组件按需拆成独立 chunk。
        //
        // vendor-vue / vendor-markdown 保留分组：前者全库共享，后者只被懒加载的
        // PromptExtensionViewer / Editor 引用（稳定、可缓存、非首屏）。
        manualChunks(id) {
          if (id.includes("node_modules/vue/") || id.includes("node_modules/@vue/")) {
            return "vendor-vue";
          }
          if (id.includes("node_modules/markdown-it/") || id.includes("node_modules/dompurify/")) {
            return "vendor-markdown";
          }
          return undefined; // element-plus 及其余模块交给 Rollup 自动分包（tree-shaking）
        },
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/argus/api": {
        target: "http://127.0.0.1:8000",
        ws: true,
      },
      "/health": "http://127.0.0.1:8000",
    },
  },
});
