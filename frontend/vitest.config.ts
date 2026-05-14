import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

// 单测专用配置，独立于 vite.config.ts：
// - 不需要 build / proxy / unplugin-vue-components 自动注册（测试只触达纯函数和 composable）
// - 强制 jsdom 环境，让 Vue effectScope / window 计时器可用
export default defineConfig({
    plugins: [vue()],
    test: {
        environment: "jsdom",
        include: ["src/**/*.{test,spec}.ts"],
        globals: false,
        clearMocks: true,
        restoreMocks: true,
    },
});
