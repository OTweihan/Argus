import { describe, expect, it } from "vitest";
import { shallowMount } from "@vue/test-utils";

import ReportView from "../ReportView.vue";
import type { ReportData } from "../../types";

const sampleReport: ReportData = {
    reportId: "r1",
    title: "测试报告",
    summary: "完成所有步骤",
    generatedAt: "2026-05-15T08:35:00Z",
    task: {
        taskId: "t1",
        projectId: "p1",
        goal: "测试登录功能",
        startUrl: "https://example.com/login",
        taskType: "blackbox",
        status: "completed",
        maxSteps: 10,
        timeoutSeconds: 300,
        captureScreenshots: true,
        currentStep: 10,
        parameters: {},
        logs: [],
        findings: [],
        createdAt: "2026-05-15T08:00:00Z",
        startedAt: "2026-05-15T08:00:05Z",
        completedAt: "2026-05-15T08:35:00Z",
        reportPath: "/reports/t1.html",
        resultSummary: "全部通过",
        errorMessage: null,
    },
    steps: [],
    findings: [],
    displaySteps: [],
    totalStepsCount: 10,
    hiddenStepsCount: 0,
};

// ReportView 在 loading / 无报告时使用 el-empty，在正常渲染时依赖多个子组件
//（ReportHero / ReportMetrics / StepCard / FindingCard）。使用 shallowMount 避免
// 子组件递归渲染，对关键结构用 mount 获取实际内容。
describe("ReportView", () => {
    it("loading 状态下 el-empty 存在", () => {
        const wrapper = shallowMount(ReportView, {
            props: { report: null, loading: true, taskId: "t1" },
        });
        // el-empty 被 stub，但其 stub 元素存在
        expect(wrapper.find("el-empty-stub").exists()).toBe(true);
    });

    it("无报告时 el-empty 存在", () => {
        const wrapper = shallowMount(ReportView, {
            props: { report: null, loading: false, taskId: "t1" },
        });
        expect(wrapper.find("el-empty-stub").exists()).toBe(true);
    });

    it("渲染报告任务信息", () => {
        const wrapper = shallowMount(ReportView, {
            props: { report: sampleReport, loading: false, taskId: "t1" },
        });
        const text = wrapper.text();
        // shallowMount 会 stub 子组件，但非组件元素（section、table 等）仍正常渲染
        expect(text).toContain("t1");
        expect(text).toContain("测试登录功能");
        expect(text).toContain("完成所有步骤");
    });

    it("渲染问题数量", () => {
        const reportWithFindings: ReportData = {
            ...sampleReport,
            findings: [
                {
                    findingId: "f1",
                    title: "安全漏洞",
                    description: "XSS 风险",
                    severity: "high",
                    findingType: "security",
                    url: "https://example.com/page",
                    location: null,
                    screenshotPath: null,
                    createdAt: "2026-05-15T08:30:00Z",
                },
            ],
        };
        const wrapper = shallowMount(ReportView, {
            props: { report: reportWithFindings, loading: false, taskId: "t1" },
        });
        // 问题数量在 section 头部显示
        expect(wrapper.text()).toContain("1 个问题");
    });

    it("执行步骤区域存在", () => {
        const wrapper = shallowMount(ReportView, {
            props: { report: sampleReport, loading: false, taskId: "t1" },
        });
        expect(wrapper.text()).toContain("执行步骤");
    });

    it("原始 JSON 折叠按钮存在", () => {
        const wrapper = shallowMount(ReportView, {
            props: { report: sampleReport, loading: false, taskId: "t1" },
        });
        const text = wrapper.text();
        expect(text).toContain("原始 JSON");
        expect(text).toContain("展开");
    });
});
