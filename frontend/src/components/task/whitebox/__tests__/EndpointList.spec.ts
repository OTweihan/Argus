import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import type { EndpointInfo } from "../../../../api/task";
import EndpointList from "../EndpointList.vue";

const endpoints = [
  {
    endpointId: "endpoint-1",
    httpMethod: "GET",
    normalizedPath: "/api/users",
    controllerClass: "UserController",
    controllerMethod: "listUsers",
  },
  {
    endpointId: "endpoint-2",
    httpMethod: "POST",
    normalizedPath: "/api/orders",
    controllerClass: "OrderController",
    controllerMethod: "createOrder",
  },
] as unknown as EndpointInfo[];

describe("EndpointList", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("防抖过滤路径，并在清空条件时立即恢复列表", async () => {
    const wrapper = mount(EndpointList, {
      props: {
        items: endpoints,
        total: 2,
        hasMore: false,
        loading: false,
      },
    });
    await flushPromises();
    vi.useFakeTimers();

    const input = wrapper.find('input[placeholder="过滤路径"]');
    await input.setValue("orders");
    expect(wrapper.findAll(".el-table__row")).toHaveLength(2);

    vi.advanceTimersByTime(220);
    await flushPromises();
    expect(wrapper.findAll(".el-table__row")).toHaveLength(1);
    expect(wrapper.text()).toContain("/api/orders");

    await input.setValue("");
    expect(wrapper.findAll(".el-table__row")).toHaveLength(2);
  });
});
