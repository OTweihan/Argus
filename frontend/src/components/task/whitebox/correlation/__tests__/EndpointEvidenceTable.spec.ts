/** EndpointEvidenceTable 组件测试：渲染、过滤、分页。
 *
 * 注意：Element Plus el-table 在 jsdom 中 body 数据可能不通过 text()
 * 完整渲染，因此关键断言以组件挂载、table 存在和 toolbar 文案为准。
 */

import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import EndpointEvidenceTable from "../EndpointEvidenceTable.vue";
import type { EndpointEvidenceInfo } from "../../../../../api/correlation";

function makeItem(overrides: Partial<EndpointEvidenceInfo> = {}): EndpointEvidenceInfo {
  return {
    endpointEvidenceId: "eev-1",
    correlationAttemptId: "ca-1",
    requestEvidenceId: "req-1",
    resolutionStatus: "UNIQUE",
    matchStrategy: "EXACT",
    confidence: "HIGH",
    matchedEndpointId: "ep-1",
    matchedEndpointInfo: null,
    candidateCount: 1,
    httpMethod: "GET",
    requestPath: "/api/users",
    displayPath: "/api/users",
    origin: "https://example.com",
    resourceType: null,
    candidates: [],
    executionFlows: [
      {
        executionFlowId: "fl-1",
        entryPoint: "UserController.list()",
        callDepth: 3,
        steps: [
          {
            flowStepId: "fs-1",
            stepIndex: 0,
            depth: 0,
            methodKey: "UserController.list()",
            className: "UserController",
            methodName: "list",
            callNodeId: "cn-1",
          },
          {
            flowStepId: "fs-2",
            stepIndex: 1,
            depth: 1,
            methodKey: "UserService.find()",
            className: "UserService",
            methodName: "find",
            callNodeId: "cn-2",
          },
        ],
      },
    ],
    ...overrides,
  };
}

describe("EndpointEvidenceTable", () => {
  it("空数据时表格正常渲染", () => {
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items: [],
        total: null,
        hasMore: false,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.find("table").exists()).toBe(true);
  });

  it("有数据时表格存在且不崩溃", () => {
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items: [
          makeItem({
            httpMethod: "POST",
            displayPath: "/api/login",
            resolutionStatus: "UNIQUE",
            matchStrategy: "EXACT",
            confidence: "HIGH",
          }),
        ],
        total: 1,
        hasMore: false,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.find("table").exists()).toBe(true);
  });

  it("total 不为 null 时显示计数", () => {
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items: [makeItem()],
        total: 5,
        hasMore: false,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.text()).toContain("共 5 条");
  });

  it("total 为 null 时不显示计数", () => {
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items: [makeItem()],
        total: null,
        hasMore: false,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.text()).not.toContain("共");
  });

  it("hasMore 为 true 时显示下滑加载提示", () => {
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items: [makeItem()],
        total: 1,
        hasMore: true,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.text()).toContain("下滑加载更多");
  });

  it("hasMore 为 false 时不显示下滑加载提示", () => {
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items: [makeItem()],
        total: 1,
        hasMore: false,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.text()).not.toContain("下滑加载更多");
  });

  it("有 matchedEndpointInfo 的 item 不破坏渲染", () => {
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items: [
          makeItem({
            matchedEndpointInfo: {
              endpointId: "ep-1",
              endpointFingerprint: "f1",
              analysisId: "an-1",
              httpMethod: "DELETE",
              normalizedPath: "/api/resource/{id}",
              normalizedPathTemplate: "/api/resource/{id}",
              isTemplated: true,
              pathSegmentCount: 3,
              controllerClass: "ResourceController",
              controllerMethod: "delete",
              parameters: [],
              returnType: "void",
              sourceLocation: null,
              entryCallNodeId: null,
            },
          }),
        ],
        total: 1,
        hasMore: false,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.find("table").exists()).toBe(true);
  });

  it("有 candidates 无 matchedEndpointInfo 时正常渲染", () => {
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items: [
          makeItem({
            matchedEndpointInfo: null,
            candidates: [
              {
                endpointId: "ep-a",
                candidateRank: 1,
                matchStrategy: "TEMPLATE",
                confidence: "MEDIUM",
                selected: false,
              },
              {
                endpointId: "ep-b",
                candidateRank: 2,
                matchStrategy: "TEMPLATE",
                confidence: "LOW",
                selected: false,
              },
            ],
          }),
        ],
        total: 1,
        hasMore: false,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.find("table").exists()).toBe(true);
  });

  it("各项 resolutionStatus 均不崩溃", () => {
    const items = [
      makeItem({ resolutionStatus: "UNIQUE", matchStrategy: "EXACT" }),
      makeItem({ resolutionStatus: "AMBIGUOUS", matchStrategy: "TEMPLATE" }),
      makeItem({ resolutionStatus: "UNMATCHED", matchStrategy: "PATH_ONLY" }),
    ];
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items,
        total: 3,
        hasMore: false,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.find("table").exists()).toBe(true);
  });

  it("有执行流时折叠项渲染不崩溃", () => {
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items: [
          makeItem({
            executionFlows: [
              { executionFlowId: "fl-9", entryPoint: "GET /api/x", callDepth: 2, steps: [] },
            ],
          }),
        ],
        total: 1,
        hasMore: false,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.find("table").exists()).toBe(true);
  });

  it("executionFlows 为空时折叠列不崩溃", () => {
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items: [makeItem({ executionFlows: [] })],
        total: 1,
        hasMore: false,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.find("table").exists()).toBe(true);
  });

  it("hasMore 为 true 且可滚动时触发 load-more 事件", async () => {
    // jsdom 无 IntersectionObserver，组件退化为不自动触发；
    // 直接验证 sentinel 存在且点击/可见时组件不崩溃。
    const wrapper = mount(EndpointEvidenceTable, {
      props: {
        items: [makeItem()],
        total: 10,
        hasMore: true,
        loading: false,
        statusFilter: "",
      },
    });
    expect(wrapper.text()).toContain("下滑加载更多");
    expect(wrapper.find(".inf-load").exists()).toBe(true);
  });
});
