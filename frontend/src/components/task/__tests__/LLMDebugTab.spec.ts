import { afterEach, describe, expect, it, vi } from "vitest";
import { shallowMount } from "@vue/test-utils";

vi.mock("../../../api", async (importOriginal) => {
    const actual = (await importOriginal()) as Record<string, unknown>;
    return { ...actual, getTaskTraces: vi.fn() };
});

import LLMDebugTab from "../LLMDebugTab.vue";
import type { LLMTraceRecord } from "../../../types";

import * as apiModule from "../../../api";
const getTaskTracesMock = apiModule.getTaskTraces as ReturnType<typeof vi.fn>;

function makeTrace(overrides: Partial<LLMTraceRecord> = {}): LLMTraceRecord {
    return {
        traceId: "tr1",
        taskId: "t1",
        phase: "planner",
        event: "task.llm.succeeded",
        model: "gpt-4",
        timestamp: "2026-05-15T08:30:00Z",
        latencyMs: 3200,
        ...overrides,
    } as LLMTraceRecord;
}

const mockTraces: LLMTraceRecord[] = [
    makeTrace({ traceId: "tr1", phase: "planner", event: "task.llm.succeeded" }),
    makeTrace({ traceId: "tr2", phase: "planner", event: "task.llm.started" }),
    makeTrace({ traceId: "tr3", phase: "evaluator", event: "task.llm.failed", model: "claude-3" }),
    makeTrace({ traceId: "tr4", phase: "evaluator", event: "task.llm.parse_failed" }),
];

describe("LLMDebugTab", () => {
    afterEach(() => {
        getTaskTracesMock.mockReset();
    });

    it("加载成功后渲染追踪列表", async () => {
        getTaskTracesMock.mockResolvedValue(mockTraces);
        const wrapper = shallowMount(LLMDebugTab, {
            props: { taskId: "t1" },
        });

        // 等待 onMounted 异步加载完成（微任务队列）
        await new Promise((r) => setTimeout(r, 0));
        await wrapper.vm.$nextTick();

        expect(wrapper.text()).toContain("gpt-4");
        expect(wrapper.text()).toContain("claude-3");
        // 默认隐藏 started
        expect(wrapper.text()).not.toContain("started");
    });

    it("显示追踪计数", async () => {
        getTaskTracesMock.mockResolvedValue(mockTraces);
        const wrapper = shallowMount(LLMDebugTab, {
            props: { taskId: "t1" },
        });

        await new Promise((r) => setTimeout(r, 0));
        await wrapper.vm.$nextTick();

        const countText = wrapper.text();
        // 4 条记录 - 1 条 started = 3 条显示
        expect(countText).toContain("3");
    });

    it("API 失败时显示错误信息", async () => {
        getTaskTracesMock.mockRejectedValue(new Error("连不上服务器"));
        const wrapper = shallowMount(LLMDebugTab, {
            props: { taskId: "t1" },
        });

        await new Promise((r) => setTimeout(r, 0));
        await wrapper.vm.$nextTick();

        expect(wrapper.text()).toContain("连不上服务器");
    });
});
