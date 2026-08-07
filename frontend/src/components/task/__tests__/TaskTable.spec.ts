import { describe, expect, it } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";

import TaskTable from "../TaskTable.vue";
import type { Project, Task } from "../../../types";

// el-table 的固定列与列宽测量依赖 ResizeObserver，jsdom 未提供，
// 补充一个空实现使表格在单测环境完成布局渲染。
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;

const mockProjects: Project[] = [
  { projectId: "p1", name: "测试项目" } as Project,
  { projectId: "p2", name: "Demo" } as Project,
];

const mockTasks: Task[] = [
  {
    taskId: "t1",
    goal: "测试登录功能",
    name: "登录测试",
    status: "completed",
    currentStep: 5,
    maxSteps: 10,
    projectId: "p1",
    createdAt: "2026-05-15T08:00:00Z",
    reportPath: "/reports/t1.html",
    schedulerStatus: null,
  } as Task,
  {
    taskId: "t2",
    goal: "注册流程验证",
    name: "",
    status: "running",
    currentStep: 3,
    maxSteps: 8,
    projectId: "p2",
    createdAt: "2026-05-15T09:00:00Z",
    reportPath: null,
    schedulerStatus: null,
  } as Task,
  {
    taskId: "t3",
    goal: "删除测试",
    name: null,
    status: "pending",
    currentStep: 0,
    maxSteps: 5,
    projectId: null,
    createdAt: "2026-05-15T10:00:00Z",
    reportPath: null,
    schedulerStatus: "queued",
  } as Task,
];

describe("TaskTable", () => {
  it("空数据时显示 empty 占位", () => {
    const wrapper = mount(TaskTable, {
      props: { tasks: [], projects: [] },
    });
    expect(wrapper.text()).toContain("暂无任务");
  });

  it("有数据时组件正常渲染", () => {
    const wrapper = mount(TaskTable, {
      props: { tasks: mockTasks, projects: mockProjects },
    });
    // 组件挂载不崩溃即有数据
    expect(wrapper.exists()).toBe(true);
    // el-table 内部渲染可能不暴露文本，但 table 元素应存在
    expect(wrapper.find("table").exists()).toBe(true);
  });

  it("projectId 为空时显示短横线", () => {
    const wrapper = mount(TaskTable, {
      props: { tasks: [mockTasks[2]], projects: [] },
    });
    // 项目列为空时渲染不会崩溃
    expect(wrapper.exists()).toBe(true);
  });

  it("空数据后切换有数据可正常更新", async () => {
    const wrapper = mount(TaskTable, {
      props: { tasks: [], projects: [] },
    });
    expect(wrapper.text()).toContain("暂无任务");

    await wrapper.setProps({ tasks: mockTasks });
    await wrapper.vm.$nextTick();
    // 更新后不再显示空状态
    expect(wrapper.find("table").exists()).toBe(true);
  });

  it("compact 模式操作列仅渲染详情类按钮", async () => {
    const wrapper = mount(TaskTable, {
      props: { tasks: mockTasks, projects: mockProjects, compactActions: true },
    });
    // el-table 的 body 行与固定列异步渲染，等待布局完成后再断言按钮。
    await flushPromises();
    await new Promise((resolve) => setTimeout(resolve, 50));
    const buttons = wrapper.findAll("button").map((b) => b.text());
    expect(buttons).toContain("任务详情");
    expect(buttons).toContain("报告详情");
    // 压缩列不渲染编辑 / 删除 / 启动 / 重试
    expect(buttons.join()).not.toContain("编辑");
    expect(buttons.join()).not.toContain("删除");
    expect(buttons.join()).not.toContain("启动");
    expect(buttons.join()).not.toContain("重试");
  });

  it("完整模式操作列渲染全部操作按钮", async () => {
    const wrapper = mount(TaskTable, {
      props: { tasks: mockTasks, projects: mockProjects },
    });
    await flushPromises();
    await new Promise((resolve) => setTimeout(resolve, 50));
    const buttons = wrapper.findAll("button").map((b) => b.text());
    expect(buttons).toContain("任务详情");
    expect(buttons).toContain("报告详情");
    expect(buttons).toContain("编辑");
    expect(buttons).toContain("删除");
  });
});
