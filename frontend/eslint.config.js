// ESLint 9 flat config（取代旧 .eslintrc.cjs）。
// 关键差异：
//   - 用 ESM 导出数组而非对象树；规则按顺序覆盖
//   - typescript-eslint v8 提供统一元包，无需手动配 plugin/parser
//   - eslint-plugin-vue 9.18+ 暴露 `configs["flat/*"]`，直接 spread 到数组里
//   - `.vue` 文件用 vue-eslint-parser 包裹后内部委托给 typescript-eslint parser

import js from "@eslint/js";
import vue from "eslint-plugin-vue";
import vueParser from "vue-eslint-parser";
import tseslint from "typescript-eslint";
import globals from "globals";

export default [
    // ── global ignores（必须单独成块）──
    {
        ignores: [
            "node_modules/**",
            "dist/**",
            // unplugin-vue-components 自动生成
            "src/components.d.ts",
            // vite/构建产物输出目录（指向后端 static）
            "../argus_py/api/static/**",
        ],
    },

    // ── 基础规则 ──
    js.configs.recommended,
    ...tseslint.configs.recommended,
    // eslint-plugin-vue 9.x 的 flat config preset 名字是 ``flat/recommended``
    // （vue3 默认）。老式 .eslintrc 里叫 ``vue/vue3-recommended``，迁移时容易混。
    ...vue.configs["flat/recommended"],

    // ── 语言/解析器配置：覆盖到 ts/vue 文件 ──
    {
        files: ["**/*.{ts,tsx,vue}"],
        languageOptions: {
            parser: vueParser,
            parserOptions: {
                // 内层用 typescript-eslint parser 处理 <script lang="ts"> 与 .ts
                parser: tseslint.parser,
                sourceType: "module",
                ecmaVersion: "latest",
                extraFileExtensions: [".vue"],
            },
            globals: {
                ...globals.browser,
                ...globals.node,
                ...globals.es2021,
            },
        },
    },

    // ── 项目自定义规则（与原 .eslintrc.cjs 一致 + 历史代码兼容降级）──
    {
        rules: {
            "@typescript-eslint/no-explicit-any": "warn",
            "vue/multi-word-component-names": "off",
            "vue/max-attributes-per-line": "off",
            // FormDialog 系列组件按 Element Plus 表单惯例直接给 ``form`` props
            // 赋值（`v-model:form`）。Vue 推荐重构为 `defineModel()` / `update:` 事件，
            // 但本项目存量场景较多，先降为 warn 让历史代码渐进迁移而不阻塞 lint。
            "vue/no-mutating-props": "warn",
        },
    },

    // ── 测试文件放宽：vitest 用 vi/expect/it 的 helper，允许更松的类型 ──
    {
        files: ["src/**/*.{spec,test}.ts"],
        rules: {
            "@typescript-eslint/no-explicit-any": "off",
            // dummyTask 等用 `as unknown as Task` 双断言
            "@typescript-eslint/no-non-null-assertion": "off",
        },
    },
];
