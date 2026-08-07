import { describe, expect, it } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import type { CallEdgeInfo, CallNodeInfo } from "../../../../api/task";
import CallGraphViewer from "../CallGraphViewer.vue";

const node = {
    callNodeId: "node-1",
    className: "com.example.UserService",
    methodName: "findUser",
} as unknown as CallNodeInfo;

const edge = {
    callEdgeId: "edge-1",
    toClassName: "com.example.UserRepository",
    toMethodName: "findById",
    resolutionType: "SYMBOL_SOLVER",
    confidence: "HIGH",
} as unknown as CallEdgeInfo;

describe("CallGraphViewer", () => {
    it("将被调用方渲染在所选节点的展开行内", async () => {
        const wrapper = mount(CallGraphViewer, {
            props: {
                items: [node],
                total: 1,
                hasMore: false,
                loading: false,
                calleeItems: [edge],
                calleeLoading: false,
                selectedNodeId: "node-1",
            },
        });
        await flushPromises();

        const detail = wrapper.find(".callee-section");
        expect(detail.exists()).toBe(true);
        expect(detail.element.closest(".el-table__expanded-cell")).not.toBeNull();
        expect(detail.text()).toContain("下游调用");
        expect(detail.text()).toContain("1 条");
        expect(detail.text()).toContain("UserRepository");
        expect(detail.text()).toContain("精确解析");
        expect(detail.text()).toContain("高置信度");
    });

    it("点击节点行时请求展开该节点", async () => {
        const wrapper = mount(CallGraphViewer, {
            props: {
                items: [node],
                total: 1,
                hasMore: false,
                loading: false,
                calleeItems: [],
                calleeLoading: false,
                selectedNodeId: null,
            },
        });
        await flushPromises();
        await wrapper.find(".el-table__row").trigger("click");

        expect(wrapper.emitted("select-node")?.[0]).toEqual(["node-1"]);
    });
});
