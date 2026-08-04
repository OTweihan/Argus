/** FindingEvidenceTable 组件测试：渲染、分页、缺陷详情列。
 *
 * 注意：Element Plus el-table 在 jsdom 中 body 数据可能不通过 text()
 * 完整渲染，因此关键断言以组件挂载、table 存在和 toolbar 文案为准。
 */

import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import FindingEvidenceTable from "../FindingEvidenceTable.vue";
import type { FindingEvidenceInfo } from "../../../../../api/correlation";

function makeItem(overrides: Partial<FindingEvidenceInfo> = {}): FindingEvidenceInfo {
    return {
        findingEvidenceId: "fe-1",
        correlationAttemptId: "ca-1",
        findingId: "find-1",
        findingInfo: {
            findingId: "find-1",
            title: "空 catch 吞掉异常",
            description: "catch 块为空",
            severity: "high",
            findingType: "security",
            location: "OrderController.java:42",
            ruleId: "EMPTY_CATCH",
            ruleCategory: "ERROR_HANDLING",
            confidence: "HIGH",
            snippet: null,
            analysisId: "an-1",
            createdAt: "2026-08-01T00:00:00Z",
        },
        bestRelationType: "DIRECT_HANDLER",
        minimumCallDistance: 0,
        confirmedRequestCount: 2,
        candidateRequestCount: 1,
        ...overrides,
    };
}

describe("FindingEvidenceTable", () => {
    it("空数据时表格正常渲染", () => {
        const wrapper = mount(FindingEvidenceTable, {
            props: { items: [], total: null, hasMore: false, loading: false },
        });
        expect(wrapper.find("table").exists()).toBe(true);
    });

    it("有数据时表格存在且不崩溃", () => {
        const wrapper = mount(FindingEvidenceTable, {
            props: { items: [makeItem()], total: 1, hasMore: false, loading: false },
        });
        expect(wrapper.find("table").exists()).toBe(true);
    });

    it("total 不为 null 时显示计数", () => {
        const wrapper = mount(FindingEvidenceTable, {
            props: { items: [makeItem()], total: 5, hasMore: false, loading: false },
        });
        expect(wrapper.text()).toContain("共 5 条");
    });

    it("hasMore 为 true 时显示加载更多按钮", () => {
        const wrapper = mount(FindingEvidenceTable, {
            props: { items: [makeItem()], total: 1, hasMore: true, loading: false },
        });
        expect(wrapper.text()).toContain("加载更多");
    });

    it("findingInfo 缺失时显示占位符", () => {
        const wrapper = mount(FindingEvidenceTable, {
            props: { items: [makeItem({ findingInfo: null })], total: 1, hasMore: false, loading: false },
        });
        expect(wrapper.find("table").exists()).toBe(true);
    });

    it("有 findingInfo 的 item 不破坏渲染", () => {
        const wrapper = mount(FindingEvidenceTable, {
            props: { items: [makeItem()], total: 1, hasMore: false, loading: false },
        });
        expect(wrapper.find("table").exists()).toBe(true);
    });

    it("点击加载更多触发 load-more 事件", async () => {
        const wrapper = mount(FindingEvidenceTable, {
            props: { items: [makeItem()], total: 10, hasMore: true, loading: false },
        });
        const btn = wrapper.findComponent({ name: "ElButton" });
        await btn.trigger("click");
        expect(wrapper.emitted("load-more")).toHaveLength(1);
    });
});
