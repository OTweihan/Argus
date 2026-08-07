import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import type { AnalysisRunSummary } from "../../../../api/task";
import CompletenessBanner from "../CompletenessBanner.vue";
import MetricsSummary from "../MetricsSummary.vue";

function summary(status: string, issues: Array<{ code: string; message: string }> = []) {
  return {
    analysisId: "analysis-1",
    runStatus: "SUCCEEDED",
    completeness: { status, issues, metrics: {} },
  } as unknown as AnalysisRunSummary;
}

describe("白盒报告摘要组件", () => {
  it("展示解析率、调用解析率和进度宽度", () => {
    const wrapper = mount(MetricsSummary, {
      props: {
        metrics: {
          eligibleSourceFiles: 20,
          parsedSourceFiles: 15,
          totalCalls: 40,
          resolvedCalls: 36,
        },
        endpointCount: 8,
        callGraphNodeCount: 24,
        findingCount: 3,
      },
    });

    expect(wrapper.text()).toContain("75%");
    expect(wrapper.text()).toContain("90%");
    const progress = wrapper.findAll(".metric-progress > span");
    expect(progress[0].attributes("style")).toContain("width: 75%");
    expect(progress[1].attributes("style")).toContain("width: 90%");
  });

  it("完整状态使用成功提示", () => {
    const wrapper = mount(CompletenessBanner, {
      props: { summary: summary("COMPLETE") },
    });
    expect(wrapper.text()).toContain("分析完整");
    expect(wrapper.find(".banner-ok").exists()).toBe(true);
  });

  it("降级状态展示质量问题", () => {
    const wrapper = mount(CompletenessBanner, {
      props: {
        summary: summary("DEGRADED", [{ code: "PARTIAL_CLASSPATH", message: "部分依赖不可用" }]),
      },
    });
    expect(wrapper.text()).toContain("分析部分降级");
    expect(wrapper.text()).toContain("PARTIAL_CLASSPATH: 部分依赖不可用");
    expect(wrapper.find(".banner-warn").exists()).toBe(true);
  });
});
