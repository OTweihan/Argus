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
        manualChunks: {
          "vendor-vue": ["vue"],
          "vendor-element-plus": ["element-plus"],
          "vendor-markdown": ["markdown-it", "dompurify"],
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
