import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";

vi.mock("../../../api", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return { ...actual, getTaskEvents: vi.fn() };
});

import TaskTimeline from "../TaskTimeline.vue";
import type { TaskEvent, TimelineEvent } from "../../../types";
import * as apiModule from "../../../api";

const getTaskEventsMock = apiModule.getTaskEvents as ReturnType<typeof vi.fn>;

function makeEvent(i: number): TimelineEvent {
  return {
    eventId: `e${i}`,
    taskId: "t1",
    eventType: "task.timeline.phase",
    phase: "run",
    stepNumber: 0,
    summary: `event ${i}`,
    data: {},
    createdAt: "2026-08-25T00:00:00Z",
  };
}

type WsSink = (event: TaskEvent) => void;

/** 组装 task.timeline.* WS 事件（组件内会把 data 断言回 TimelineEvent）。 */
function wsEvent(event: TimelineEvent): TaskEvent {
  return {
    eventType: "task.timeline.x",
    taskId: "t1",
    data: event as unknown as Record<string, unknown>,
  };
}

/** 挂载并捕获 onTaskEvent 注册的 WS 回调。 */
async function mountWithWs(): Promise<{
  wrapper: ReturnType<typeof mount>;
  push: WsSink;
}> {
  let sink: WsSink = () => {};
  const wrapper = mount(TaskTimeline, {
    props: {
      taskId: "t1",
      onTaskEvent: (cb: (event: TaskEvent) => void) => {
        sink = cb;
        return () => {};
      },
    },
  });
  // 初始 loadEvents 的 mock resolve 微任务
  await new Promise((r) => setTimeout(r, 0));
  await wrapper.vm.$nextTick();
  return { wrapper, push: sink };
}

describe("TaskTimeline 事件去重与有界缓冲", () => {
  it("WS 推送重复 eventId 不重复入列（Set 幂等索引）", async () => {
    getTaskEventsMock.mockResolvedValue([]);
    const { wrapper, push } = await mountWithWs();

    push(wsEvent(makeEvent(1)));
    push(wsEvent(makeEvent(1)));
    await wrapper.vm.$nextTick();

    const events = (wrapper.vm as unknown as { events: TimelineEvent[] }).events;
    expect(events).toHaveLength(1);
    expect(events[0].eventId).toBe("e1");
  });

  it("超过 MAX_EVENTS 时丢弃最旧事件，保留最新", async () => {
    getTaskEventsMock.mockResolvedValue([]);
    const { wrapper, push } = await mountWithWs();

    for (let i = 0; i < 2001; i++) {
      push(wsEvent(makeEvent(i)));
    }
    await wrapper.vm.$nextTick();

    const events = (wrapper.vm as unknown as { events: TimelineEvent[] }).events;
    expect(events).toHaveLength(2000);
    expect(events[0].eventId).toBe("e1");
    expect(events[1999].eventId).toBe("e2000");
  });

  it("权威重拉后重建去重索引：重放已见事件不产生重复", async () => {
    getTaskEventsMock.mockResolvedValue([makeEvent(1), makeEvent(2)]);
    const { wrapper, push } = await mountWithWs();

    // 服务端列表已含 e2；重放 e2 + 新增 e3 不得出现重复
    push(wsEvent(makeEvent(2)));
    push(wsEvent(makeEvent(3)));
    await wrapper.vm.$nextTick();

    const events = (wrapper.vm as unknown as { events: TimelineEvent[] }).events;
    expect(events.map((e) => e.eventId)).toEqual(["e1", "e2", "e3"]);
  });

  it("初始加载超上限时同样截断为最近 MAX_EVENTS 条", async () => {
    getTaskEventsMock.mockResolvedValue(
      Array.from({ length: 2500 }, (_, i) => makeEvent(i)),
    );
    const { wrapper } = await mountWithWs();

    const events = (wrapper.vm as unknown as { events: TimelineEvent[] }).events;
    expect(events).toHaveLength(2000);
    expect(events[0].eventId).toBe("e500");
    expect(events[1999].eventId).toBe("e2499");
  });
});
