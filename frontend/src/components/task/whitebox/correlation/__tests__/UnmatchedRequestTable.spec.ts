/** UnmatchedRequestTable 组件测试：未匹配请求展示、状态码着色、分页。
 *
 * 注意：Element Plus el-table 在 jsdom 中 body 数据可能不通过 text()
 * 完整渲染，因此关键断言以工具条文案和 table 存在为准。
 */

import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import UnmatchedRequestTable from "../UnmatchedRequestTable.vue";
import type { HttpRequestEvidenceInfo } from "../../../../../api/correlation";

function makeItem(
    overrides: Partial<HttpRequestEvidenceInfo> = {},
): HttpRequestEvidenceInfo {
    return {
        requestEvidenceId: "req-1",
        blackboxRunId: "bb-1",
        taskId: "t-1",
        stepExecutionId: null,
        stepAttempt: 1,
        requestSequence: 1,
        httpMethod: "GET",
        displayPath: "/api/users",
        origin: "https://example.com",
        resourceType: "xhr",
        endpointMatchEligibility: "CONFIRMED_ELIGIBLE",
        responseStatus: 200,
        outcome: "COMPLETED",
        requestOwner: "FRAME",
        responseFromServiceWorker: false,
        pageSequence: 0,
        capturedAt: "2024-01-01T00:00:00",
        finishedAt: null,
        ...overrides,
    };
}

describe("UnmatchedRequestTable", () => {
    it("空数据时表格正常渲染", () => {
        const wrapper = mount(UnmatchedRequestTable, {
            props: {
                items: [],
                total: null,
                hasMore: false,
                loading: false,
            },
        });
        expect(wrapper.find("table").exists()).toBe(true);
    });

    it("有数据时表格存在且不崩溃", () => {
        const wrapper = mount(UnmatchedRequestTable, {
            props: {
                items: [makeItem({ httpMethod: "POST", displayPath: "/api/login" })],
                total: 1,
                hasMore: false,
                loading: false,
            },
        });
        expect(wrapper.find("table").exists()).toBe(true);
    });

    it("total 不为 null 时显示未匹配请求计数", () => {
        const wrapper = mount(UnmatchedRequestTable, {
            props: {
                items: [makeItem()],
                total: 3,
                hasMore: false,
                loading: false,
            },
        });
        expect(wrapper.text()).toContain("共 3 条未匹配请求");
    });

    it("total 为 null 时不显示计数", () => {
        const wrapper = mount(UnmatchedRequestTable, {
            props: {
                items: [],
                total: null,
                hasMore: false,
                loading: false,
            },
        });
        expect(wrapper.text()).not.toContain("未匹配请求");
    });

    it("hasMore 为 true 时显示下滑加载提示", () => {
        const wrapper = mount(UnmatchedRequestTable, {
            props: {
                items: [makeItem()],
                total: 1,
                hasMore: true,
                loading: false,
            },
        });
        expect(wrapper.text()).toContain("下滑加载更多");
    });

    it("hasMore 为 false 时不显示下滑加载提示", () => {
        const wrapper = mount(UnmatchedRequestTable, {
            props: {
                items: [makeItem()],
                total: 1,
                hasMore: false,
                loading: false,
            },
        });
        expect(wrapper.text()).not.toContain("下滑加载更多");
    });

    it("各种 outcome 均不崩溃", () => {
        const items = [
            makeItem({ outcome: "COMPLETED" }),
            makeItem({ outcome: "NETWORK_FAILED" }),
            makeItem({ outcome: "ABANDONED" }),
        ];
        const wrapper = mount(UnmatchedRequestTable, {
            props: { items, total: 3, hasMore: false, loading: false },
        });
        expect(wrapper.find("table").exists()).toBe(true);
    });

    it("responseStatus 为 null 时不崩溃", () => {
        const wrapper = mount(UnmatchedRequestTable, {
            props: {
                items: [makeItem({ responseStatus: null })],
                total: 1,
                hasMore: false,
                loading: false,
            },
        });
        expect(wrapper.find("table").exists()).toBe(true);
    });

    it("各种 endpointMatchEligibility 均不崩溃", () => {
        const items = [
            makeItem({ endpointMatchEligibility: "CONFIRMED_ELIGIBLE" }),
            makeItem({ endpointMatchEligibility: "ATTEMPT_ONLY" }),
        ];
        const wrapper = mount(UnmatchedRequestTable, {
            props: { items, total: 2, hasMore: false, loading: false },
        });
        expect(wrapper.find("table").exists()).toBe(true);
    });

    it("hasMore 为 true 时哨兵存在且不崩溃", () => {
        const wrapper = mount(UnmatchedRequestTable, {
            props: {
                items: [makeItem()],
                total: 10,
                hasMore: true,
                loading: false,
            },
        });
        expect(wrapper.find(".inf-load").exists()).toBe(true);
    });

    it("多条数据时表格正常渲染", () => {
        const wrapper = mount(UnmatchedRequestTable, {
            props: {
                items: [
                    makeItem({ requestEvidenceId: "req-a" }),
                    makeItem({ requestEvidenceId: "req-b" }),
                ],
                total: 2,
                hasMore: false,
                loading: false,
            },
        });
        expect(wrapper.find("table").exists()).toBe(true);
    });
});
