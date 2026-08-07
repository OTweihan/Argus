import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import type { DiagnosticsInfo } from "../../../../api/task";
import DiagnosticsPanel from "../DiagnosticsPanel.vue";

const diagnostics = {
  totalSourceFiles: 487,
  eligibleSourceFiles: 487,
  parsedFileCount: 487,
  failedFileCount: 0,
  failedFiles: [],
  totalCalls: 7041,
  resolvedHigh: 3880,
  resolvedMedium: 1965,
  resolvedLow: 0,
  unresolved: 1196,
  classpathAvailable: true,
  jarCount: 679,
  classpathSource: "module-aware",
  moduleCount: 32,
  applicationModuleCount: 3,
  classpathWarnings: [],
  classpathErrors: [],
} as unknown as DiagnosticsInfo;

describe("DiagnosticsPanel", () => {
  it("以左对齐统计网格展示源码解析数据", () => {
    const wrapper = mount(DiagnosticsPanel, { props: { diagnostics } });
    const stats = wrapper.findAll(".source-stat");
    expect(stats).toHaveLength(4);
    expect(stats[0].text()).toContain("源文件总数");
    expect(stats[0].text()).toContain("487");
    expect(wrapper.find(".stat-number").classes()).toContain("stat-number");
  });

    it("明确展示调用解析率与置信度分布", () => {
    const wrapper = mount(DiagnosticsPanel, { props: { diagnostics } });
    expect(wrapper.find(".call-total").text()).toContain("调用总数7041");
    expect(wrapper.find(".call-resolution-rate").text()).toContain("已解析 5845 条83%");
    expect(wrapper.find(".call-stat.high").text()).toContain("高置信度3880");
    expect(wrapper.find(".call-stat.unresolved").text()).toContain("未解析1196");
        expect(wrapper.findAll(".distribution-bar .segment")).toHaveLength(4);
    });

    it("以状态面板和统计卡展示 Classpath", () => {
        const wrapper = mount(DiagnosticsPanel, { props: { diagnostics } });
        expect(wrapper.find(".classpath-status.available").text()).toContain("依赖环境可用");
        expect(wrapper.find(".classpath-source-stat").text()).toContain("module-aware");
        const stats = wrapper.findAll(".classpath-stat").map((item) => item.text());
        expect(stats).toContain("JAR 依赖679");
        expect(stats).toContain("模块总数32");
        expect(stats).toContain("应用模块3");
    });

    it("Classpath 不可用时突出显示错误和警告", () => {
        const unavailable = {
            ...diagnostics,
            classpathAvailable: false,
            classpathWarnings: ["部分依赖未解析"],
            classpathErrors: ["Maven 执行失败"],
        } as DiagnosticsInfo;
        const wrapper = mount(DiagnosticsPanel, { props: { diagnostics: unavailable } });
        expect(wrapper.find(".classpath-status.unavailable").text()).toContain("依赖环境不可用");
        expect(wrapper.find(".classpath-message.warning").text()).toContain("部分依赖未解析");
        expect(wrapper.find(".classpath-message.error").text()).toContain("Maven 执行失败");
    });
});
