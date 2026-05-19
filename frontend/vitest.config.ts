import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";

// 单测专用配置，独立于 vite.config.ts：
// - 不需要 build / proxy
// - 强制 jsdom 环境，让 Vue effectScope / window 计时器可用
// - 启用 unplugin-vue-components 使模板中的 <el-xxx> 在 ut 中也可解析
export default defineConfig({
    plugins: [
        vue(),
        Components({
            resolvers: [ElementPlusResolver()],
            dts: "src/components.d.ts",
        }),
    ],
    test: {
        environment: "jsdom",
        include: ["src/**/*.{test,spec}.ts"],
        globals: false,
        clearMocks: true,
        restoreMocks: true,
        server: {
            deps: {
                inline: ["element-plus"],
            },
        },
    },
});
