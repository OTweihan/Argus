import {describe, expect, it} from "vitest";

import {
    REPORT_NAV_ITEMS,
    formatDate,
    getReportSummary,
    getStatusLabel,
    prettyJson,
} from "../reportUtils";

describe("reportUtils.formatDate", () => {
    it("空值返回 dash 占位", () => {
        expect(formatDate(null)).toBe("-");
        expect(formatDate("")).toBe("-");
    });

    it("非法时间字符串原样返回", () => {
        expect(formatDate("not-a-date")).toBe("not-a-date");
    });

    it("合法 ISO 时间返回 zh-CN 格式串", () => {
        const out = formatDate("2026-05-15T08:30:00Z");
        // 不强校验具体 locale 渲染，但应当包含 2026 与冒号分隔；
        // 与单元运行环境 timezone 无关，仅验证函数走通格式化分支。
        expect(out).toMatch(/2026/);
        expect(out).toMatch(/:/);
    });
});

describe("reportUtils.prettyJson", () => {
    it("缩进 2 空格序列化对象", () => {
        const out = prettyJson({a: 1, b: [2, 3]});
        expect(out).toBe(`{\n  "a": 1,\n  "b": [\n    2,\n    3\n  ]\n}`);
    });

    it("undefined 返回 undefined（保留 JSON.stringify 行为）", () => {
        expect(prettyJson(undefined)).toBeUndefined();
    });
});

describe("reportUtils.REPORT_NAV_ITEMS", () => {
    it("顺序与 ReportView 模板 section ID 一致", () => {
        expect(REPORT_NAV_ITEMS.map((i) => i.id)).toEqual([
            "overview",
            "task",
            "steps",
            "findings",
            "raw-json",
        ]);
    });

    it("不可变（Object.freeze）", () => {
        expect(Object.isFrozen(REPORT_NAV_ITEMS)).toBe(true);
    });

    it("索引格式为两位字符串", () => {
        for (const item of REPORT_NAV_ITEMS) {
            expect(item.index).toMatch(/^\d{2}$/);
            expect(item.label.length).toBeGreaterThan(0);
        }
    });
});

describe("reportUtils.getStatusLabel", () => {
    it("已知状态返回中文映射", () => {
        expect(getStatusLabel("completed")).toBe("已完成");
        expect(getStatusLabel("failed")).toBe("失败");
        expect(getStatusLabel("running")).toBe("运行中");
        expect(getStatusLabel("pending")).toBe("等待中");
        expect(getStatusLabel("timeout")).toBe("超时");
        expect(getStatusLabel("cancelled")).toBe("已取消");
    });

    it("未知状态原样返回", () => {
        expect(getStatusLabel("unknown-state")).toBe("unknown-state");
    });

    it("空值返回空串，避免 UI 出现 'null' / 'undefined' 字面量", () => {
        expect(getStatusLabel(null)).toBe("");
        expect(getStatusLabel(undefined)).toBe("");
        expect(getStatusLabel("")).toBe("");
    });
});

describe("reportUtils.getReportSummary", () => {
    it("优先取 report.summary", () => {
        const out = getReportSummary({
            summary: "顶层 summary",
            task: {result_summary: "任务级 summary"},
        });
        expect(out).toBe("顶层 summary");
    });

    it("顶层缺失时回落到 task.result_summary", () => {
        const out = getReportSummary({
            summary: null,
            task: {result_summary: "任务级 summary"},
        });
        expect(out).toBe("任务级 summary");
    });

    it("两者均空时返回默认提示", () => {
        expect(getReportSummary({summary: "", task: {result_summary: ""}})).toBe(
            "未记录结果摘要。",
        );
        expect(getReportSummary({summary: null, task: null})).toBe("未记录结果摘要。");
    });

    it("null / undefined 报告返回默认提示", () => {
        expect(getReportSummary(null)).toBe("未记录结果摘要。");
        expect(getReportSummary(undefined)).toBe("未记录结果摘要。");
    });
});
