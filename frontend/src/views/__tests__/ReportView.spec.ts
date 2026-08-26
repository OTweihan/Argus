import { describe, expect, it } from "vitest";
import { flushPromises, shallowMount, type VueWrapper } from "@vue/test-utils";

import ReportView from "../ReportView.vue";
import type { ReportData, ReportTaskLog } from "../../types";

/** 激活指定页签（懒挂载分区需先激活才挂载）。 */
async function activateTab(wrapper: VueWrapper, index: number): Promise<void> {
  await wrapper.findAll(".nav-link")[index].trigger("click");
  await flushPromises();
}

function makeStep(i: number): ReportTaskLog {
  return {
    stepNumber: i + 1,
    action: "navigate",
    result: "success",
    taskLogId: `log-${i}`,
    params: {},
    urlBefore: null,
    urlAfter: "https://example.com/page",
    screenshotPath: null,
    message: null,
    error: null,
    errorCode: null,
    createdAt: "2026-05-15T08:00:00Z",
  };
}

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

  it("实时任务状态优先于报告生成时快照", () => {
    const runningSnapshot: ReportData = {
      ...sampleReport,
      task: { ...sampleReport.task, status: "running" },
    };
    const wrapper = shallowMount(ReportView, {
      props: {
        report: runningSnapshot,
        loading: false,
        taskId: "t1",
        taskStatus: "completed",
      },
    });

    expect(wrapper.getComponent({ name: "ReportHero" }).props("status")).toBe("completed");
    expect(wrapper.getComponent({ name: "ReportMetrics" }).props("statusLabel")).toBe("已完成");
  });

  it("渲染问题数量（findings 页签激活后）", async () => {
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
    // 问题数量在 findings 分区头部显示；该分区懒挂载，需先激活
    await activateTab(wrapper, 2);
    expect(wrapper.text()).toContain("1 个问题");
  });

  it("重组件分区懒挂载：首次激活才渲染，之后保留 DOM", async () => {
    const wrapper = shallowMount(ReportView, {
      props: { report: sampleReport, loading: false, taskId: "t1" },
    });
    // 初始仅 overview 挂载
    expect(wrapper.find("#report-panel-steps").exists()).toBe(false);
    expect(wrapper.find("#report-panel-findings").exists()).toBe(false);
    expect(wrapper.find("#report-panel-raw-json").exists()).toBe(false);

    // 激活 steps 后挂载
    await activateTab(wrapper, 1);
    expect(wrapper.find("#report-panel-steps").exists()).toBe(true);
    expect(wrapper.text()).toContain("执行步骤");

    // 切回 overview 后 steps 分区保留 DOM（仅 v-show 隐藏）
    await activateTab(wrapper, 0);
    expect(wrapper.find("#report-panel-steps").exists()).toBe(true);
  });

  it("原始 JSON 区域懒挂载：激活前不渲染大文本块", async () => {
    const wrapper = shallowMount(ReportView, {
      props: { report: sampleReport, loading: false, taskId: "t1" },
    });
    expect(wrapper.find(".json-block").exists()).toBe(false);

    await activateTab(wrapper, 3);
    expect(wrapper.text()).toContain("复制");
    expect(wrapper.find(".json-block").exists()).toBe(true);
  });

  it("步骤列表超过渲染上限时仅渲染前 RENDER_CAP 条并提示", async () => {
    const manySteps: ReportData = {
      ...sampleReport,
      displaySteps: Array.from({ length: 600 }, (_, i) => makeStep(i)),
    };
    const wrapper = shallowMount(ReportView, {
      props: { report: manySteps, loading: false, taskId: "t1" },
    });
    await activateTab(wrapper, 1);

    const cards = wrapper.findAllComponents({ name: "StepCard" });
    expect(cards).toHaveLength(500);
    // 触顶提示存在，统计仍按全量数据计算
    expect(wrapper.find("render-cap-hint-stub").exists()).toBe(true);
    expect(wrapper.text()).toContain("全部步骤");
  });
});
