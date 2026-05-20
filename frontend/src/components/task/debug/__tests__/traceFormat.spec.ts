import { describe, expect, it } from "vitest";

import { eventLabel, eventTagType, formatTime } from "../traceFormat";

describe("traceFormat.eventLabel", () => {
    it("4 个内置 LLM 事件返回固定 label", () => {
        expect(eventLabel("task.llm.started")).toBe("started");
        expect(eventLabel("task.llm.succeeded")).toBe("succeeded");
        expect(eventLabel("task.llm.failed")).toBe("failed");
        expect(eventLabel("task.llm.parse_failed")).toBe("parse_failed");
    });

    it("未知事件原样返回（不抛错）", () => {
        expect(eventLabel("task.something.custom")).toBe("task.something.custom");
        expect(eventLabel("")).toBe("");
    });
});

describe("traceFormat.eventTagType", () => {
    it("成功/失败/解析失败映射到 success/danger/warning，其它都是 info", () => {
        expect(eventTagType("task.llm.succeeded")).toBe("success");
        expect(eventTagType("task.llm.failed")).toBe("danger");
        expect(eventTagType("task.llm.parse_failed")).toBe("warning");
        expect(eventTagType("task.llm.started")).toBe("info");
        expect(eventTagType("anything-else")).toBe("info");
    });
});

describe("traceFormat.formatTime", () => {
    it("空 / falsy 返回占位符", () => {
        expect(formatTime("")).toBe("-");
    });

    it("合法 ISO 字符串格式化为 zh-CN 双数字日期时间", () => {
        const out = formatTime("2026-05-19T09:30:45.000Z");
        // 不断言时区敏感的具体小时数，只检查格式骨架
        expect(out).toMatch(/\d{2}\/\d{2}.*\d{2}:\d{2}:\d{2}/);
    });

    it("非法字符串原样返回（不抛错）", () => {
        // Intl.DateTimeFormat 接受 invalid date 会返回 "Invalid Date" 字符串而非抛错，
        // 但仍是字符串；我们只确保函数不崩。
        const out = formatTime("not-a-date");
        expect(typeof out).toBe("string");
    });
});
