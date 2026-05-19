import { afterEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";

vi.mock("../../../api", async (importOriginal) => {
    const actual = (await importOriginal()) as Record<string, unknown>;
    return { ...actual, previewPrompt: vi.fn() };
});

import PromptExtensionEditor from "../PromptExtensionEditor.vue";
import { emptyPromptExtensions } from "../../../promptExtensions";

// 复用现有 composable/__tests__ 的 mock 模式：模块级 mock 后取被 mock 的函数。
import * as apiModule from "../../../api";
const previewMock = apiModule.previewPrompt as ReturnType<typeof vi.fn>;

function createWrapper(overrides: Record<string, unknown> = {}) {
    return mount(PromptExtensionEditor, {
        props: {
            modelValue: emptyPromptExtensions(),
            scope: "task",
            projectExtensions: emptyPromptExtensions(),
            ...overrides,
        },
        attachTo: document.body,
    });
}

describe("PromptExtensionEditor", () => {
    afterEach(() => {
        previewMock.mockReset();
    });

    it("渲染两个角色 Tab（planner / evaluator）", () => {
        const wrapper = createWrapper();
        expect(wrapper.text()).toContain("Planner");
        expect(wrapper.text()).toContain("Evaluator");
    });

    it("输入内容时发出 update:modelValue", async () => {
        const wrapper = createWrapper();
        const textarea = wrapper.find("textarea");
        expect(textarea.exists()).toBe(true);

        await textarea.setValue("自定义规则");
        const emitted = wrapper.emitted("update:modelValue");
        expect(emitted).toHaveLength(1);
        const payload = emitted![0][0] as { planner: string; evaluator: string };
        expect(payload.planner).toBe("自定义规则");
    });

    it("空内容时显示占位文字", () => {
        const wrapper = createWrapper({ scope: "project" });
        const text = wrapper.text();
        expect(text).toContain("未填写扩展内容");
    });

    it("完整 system_prompt 预览折叠面板存在", () => {
        const wrapper = createWrapper();
        expect(wrapper.text()).toContain("system_prompt");
    });

    it("scope=task 且无 projectExtensions 时不会崩溃", () => {
        const wrapper = createWrapper({
            scope: "task",
            projectExtensions: undefined,
        });
        expect(wrapper.exists()).toBe(true);
    });
});
