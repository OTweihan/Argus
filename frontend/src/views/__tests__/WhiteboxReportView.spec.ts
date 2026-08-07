/** WhiteboxReportView 白盒结果页测试：tab 渲染、run selector、关联证据 tab。
 *
 * 使用 shallowMount + mock api 模块，聚焦页面编排逻辑，不渲染各 tab 子组件。
 * el-tab-pane 的 label 在 tabs 头中渲染（即使 lazy），可经 text() 断言。
 */

import { describe, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";

vi.mock("../../api/task", () => ({
  listAnalysisRuns: vi.fn(),
  getAnalysisRunSummary: vi.fn(),
  listAnalysisEndpoints: vi.fn(),
  listAnalysisCallNodes: vi.fn(),
  listAnalysisCallEdges: vi.fn(),
  listAnalysisExecutionFlows: vi.fn(),
  getAnalysisDiagnostics: vi.fn(),
  listAnalysisFindings: vi.fn(),
  listAnalysisClusters: vi.fn(),
}));
vi.mock("../../api/correlation", () => ({
  listCorrelationRunsByTask: vi.fn(),
}));

import * as taskApi from "../../api/task";
import * as corrApi from "../../api/correlation";
import WhiteboxReportView from "../../components/task/WhiteboxReportView.vue";

const runs = [
  {
    analysisId: "an-1",
    taskId: "t-1",
    runStatus: "SUCCEEDED",
    sourceSnapshotId: "src-1",
    resolvedCommitSha: "abc123",
    completenessStatus: "COMPLETE",
  },
];

function mockPage() {
  return { items: [], total: 0, hasMore: false, nextCursor: null };
}

function mockRuns() {
  (taskApi.listAnalysisRuns as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: runs,
    total: 1,
    hasMore: false,
    nextCursor: null,
  });
  (taskApi.getAnalysisRunSummary as ReturnType<typeof vi.fn>).mockResolvedValue({
    analysisId: "an-1",
    runStatus: "SUCCEEDED",
    completenessStatus: "COMPLETE",
    qualityIssues: [],
    severityCounts: {},
  });
  // 子 tab 懒加载接口的默认空分页（切换 run / tab 时触发）
  (taskApi.listAnalysisEndpoints as ReturnType<typeof vi.fn>).mockResolvedValue(mockPage());
  (taskApi.listAnalysisCallNodes as ReturnType<typeof vi.fn>).mockResolvedValue(mockPage());
  (taskApi.listAnalysisCallEdges as ReturnType<typeof vi.fn>).mockResolvedValue(mockPage());
  (taskApi.listAnalysisExecutionFlows as ReturnType<typeof vi.fn>).mockResolvedValue(mockPage());
  (taskApi.listAnalysisFindings as ReturnType<typeof vi.fn>).mockResolvedValue(mockPage());
  (taskApi.listAnalysisClusters as ReturnType<typeof vi.fn>).mockResolvedValue(mockPage());
  (taskApi.getAnalysisDiagnostics as ReturnType<typeof vi.fn>).mockResolvedValue({});
}

// 白盒子组件 stub：保留真实 el-tabs/el-tab-pane 以断言 tab 头文案
const WHITEBOX_CHILD_STUBS = {
  OverviewTab: true,
  AnalysisRunSelector: true,
  AnalysisSnapshotBar: true,
  CompletenessBanner: true,
  EndpointList: true,
  CallGraphViewer: true,
  ExecutionFlowList: true,
  DiagnosticsPanel: true,
  ClusterList: true,
  FindingList: true,
  CorrelationTab: true,
};

async function mountView(taskId: string) {
  const wrapper = mount(WhiteboxReportView, {
    props: { taskId },
    global: { stubs: WHITEBOX_CHILD_STUBS },
  });
  await flushPromises();
  return wrapper;
}

const BASE_TABS = ["概览", "端点", "调用关系", "执行流", "诊断", "聚类", "发现项"];

describe("WhiteboxReportView", () => {
  it("无分析执行时显示 empty 占位", async () => {
    (taskApi.listAnalysisRuns as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      total: 0,
      hasMore: false,
      nextCursor: null,
    });
    (corrApi.listCorrelationRunsByTask as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const wrapper = await mountView("t-none");
    expect(wrapper.text()).toContain("暂无分析执行数据");
  });

  it("有分析时渲染 run selector 与基础 tab", async () => {
    mockRuns();
    (corrApi.listCorrelationRunsByTask as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const wrapper = await mountView("t-1");

    expect(taskApi.getAnalysisRunSummary).toHaveBeenCalledWith("t-1", "an-1");
    const text = wrapper.text();
    expect(text).toContain("白盒分析报告");
    expect(text).toContain("查看源码解析质量、调用关系与风险发现");
    expect(wrapper.findComponent({ name: "AnalysisSnapshotBar" }).exists()).toBe(true);
    expect(wrapper.findComponent({ name: "CompletenessBanner" }).exists()).toBe(true);
    for (const label of BASE_TABS) {
      expect(text).toContain(label);
    }
    // 无关联运行时不应渲染关联证据 tab
    expect(text).not.toContain("关联证据");
  });

  it("存在关联运行时渲染关联证据 tab", async () => {
    mockRuns();
    (corrApi.listCorrelationRunsByTask as ReturnType<typeof vi.fn>).mockResolvedValue([
      { correlationRunId: "cr-1" },
    ]);
    const wrapper = await mountView("t-1");
    expect(wrapper.text()).toContain("关联证据");
  });

  it("切换 run 时刷新 summary", async () => {
    mockRuns();
    (corrApi.listCorrelationRunsByTask as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const wrapper = await mountView("t-1");
    const selector = wrapper.findComponent({ name: "AnalysisRunSelector" });
    expect(selector.exists()).toBe(true);
    selector.vm.$emit("select", "an-2");
    await flushPromises();
    expect(taskApi.getAnalysisRunSummary).toHaveBeenCalledWith("t-1", "an-2");
  });
});
