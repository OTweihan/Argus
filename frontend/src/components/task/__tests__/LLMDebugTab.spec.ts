import { afterEach, describe, expect, it, vi } from "vitest";
import { shallowMount } from "@vue/test-utils";

vi.mock("../../../api", async (importOriginal) => {
    const actual = (await importOriginal()) as Record<string, unknown>;
    return { ...actual, getTaskTraces: vi.fn() };
});

import LLMDebugTab from "../LLMDebugTab.vue";
import TraceListPanel from "../debug/TraceListPanel.vue";
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

async function flush(): Promise<void> {
    await new Promise((r) => setTimeout(r, 0));
}

describe("LLMDebugTab", () => {
    afterEach(() => {
        getTaskTracesMock.mockReset();
    });

    it("加载成功后把过滤后的 traces 传给 TraceListPanel（默认隐藏 started）", async () => {
        getTaskTracesMock.mockResolvedValue(mockTraces);
        const wrapper = shallowMount(LLMDebugTab, {
            props: { taskId: "t1" },
        });

        // useTraceList 在 watch immediate 里触发 loadTraces，要等 mock 的 resolve 微任务
        await flush();
        await wrapper.vm.$nextTick();

        const listPanel = wrapper.findComponent(TraceListPanel);
        expect(listPanel.exists()).toBe(true);
        const passed = listPanel.props("traces") as LLMTraceRecord[];
        // 4 条记录 - 1 条 started = 3 条
        expect(passed).toHaveLength(3);
        expect(passed.map((t) => t.model)).toContain("gpt-4");
        expect(passed.map((t) => t.model)).toContain("claude-3");
        expect(passed.every((t) => t.event !== "task.llm.started")).toBe(true);
    });

    it("hideStarted=false 时把 started 项也透传", async () => {
        getTaskTracesMock.mockResolvedValue(mockTraces);
        const wrapper = shallowMount(LLMDebugTab, {
            props: { taskId: "t1" },
        });
        await flush();
        await wrapper.vm.$nextTick();

        const listPanel = wrapper.findComponent(TraceListPanel);
        // 模拟用户在子组件里取消勾选 → emit update:hideStarted=false
        listPanel.vm.$emit("update:hideStarted", false);
        await wrapper.vm.$nextTick();

        const passed = listPanel.props("traces") as LLMTraceRecord[];
        expect(passed).toHaveLength(4);
    });

    it("API 失败时把 errorMessage 透传到 TraceListPanel.loadError", async () => {
        getTaskTracesMock.mockRejectedValue(new Error("连不上服务器"));
        const wrapper = shallowMount(LLMDebugTab, {
            props: { taskId: "t1" },
        });

        await flush();
        await wrapper.vm.$nextTick();

        const listPanel = wrapper.findComponent(TraceListPanel);
        expect(listPanel.props("loadError")).toBe("连不上服务器");
        expect(listPanel.props("traces")).toEqual([]);
    });
});
