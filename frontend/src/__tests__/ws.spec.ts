import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearApiToken } from "../auth";
import type { TaskEvent } from "../types";
import { reconnectDelayMs, TaskEventStream, type ReplayGapInfo } from "../ws";

class MockWebSocket {
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static instances: MockWebSocket[] = [];

  readonly url: string;
  readyState = MockWebSocket.OPEN;
  private listeners = new Map<string, ((payload?: unknown) => void)[]>();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: (payload?: unknown) => void): void {
    const callbacks = this.listeners.get(type) ?? [];
    callbacks.push(listener);
    this.listeners.set(type, callbacks);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSING;
  }

  emit(type: string, payload?: unknown): void {
    for (const cb of this.listeners.get(type) ?? []) cb(payload);
  }
}

function send(ws: MockWebSocket, event: TaskEvent): void {
  ws.emit("message", { data: JSON.stringify(event) });
}

function readyEvent(epoch: string, oldest = 1, current = 1): TaskEvent {
  return {
    eventType: "system.ready",
    data: {
      streamEpoch: epoch,
      oldestSequence: oldest,
      currentSequence: current,
      replayComplete: true,
    },
  };
}

function replayGapEvent(info: Partial<ReplayGapInfo> = {}): TaskEvent {
  return {
    eventType: "system.replay_gap",
    data: {
      reason: "epoch_changed",
      streamEpoch: "ev-new",
      oldestSequence: 1,
      currentSequence: 10,
      ...info,
    },
  };
}

describe("TaskEventStream — replay gap / epoch 处理", () => {
  beforeEach(() => {
    clearApiToken();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    clearApiToken();
  });

  it("首次 system.ready 记录纪元，不触发 replay gap", () => {
    const stream = new TaskEventStream();
    const onGap = vi.fn();
    stream.onReplayGap(onGap);

    stream.connect();
    send(MockWebSocket.instances[0], readyEvent("ev-A"));

    expect(onGap).not.toHaveBeenCalled();
    const internal = stream as unknown as { streamEpoch: string | undefined };
    expect(internal.streamEpoch).toBe("ev-A");
    stream.close();
  });

  it("重连后纪元变化（服务重启）触发 epoch_changed 并清空旧游标", () => {
    const stream = new TaskEventStream();
    const onGap = vi.fn();
    stream.onReplayGap(onGap);

    stream.connect();
    send(MockWebSocket.instances[0], readyEvent("ev-A"));
    // 收到一条任务事件，lastSequence 推进
    send(MockWebSocket.instances[0], {
      sequence: 42,
      eventType: "task.updated",
      taskId: "t1",
      data: {},
    });
    const internal = stream as unknown as {
      lastSequence: number | undefined;
      streamEpoch: string | undefined;
    };
    expect(internal.lastSequence).toBe(42);

    // 模拟服务重启后重连
    stream.close();
    stream.connect();
    send(MockWebSocket.instances[1], readyEvent("ev-B"));

    expect(onGap).toHaveBeenCalledTimes(1);
    const info = onGap.mock.calls[0][0] as ReplayGapInfo;
    expect(info.reason).toBe("epoch_changed");
    expect(info.streamEpoch).toBe("ev-B");
    // 旧纪元的高 sequence 失效，游标被清空
    expect(internal.lastSequence).toBeUndefined();
    stream.close();
  });

  it("system.replay_gap 触发 onReplayGap 并清空游标", () => {
    const stream = new TaskEventStream();
    const onGap = vi.fn();
    stream.onReplayGap(onGap);

    stream.connect();
    send(MockWebSocket.instances[0], {
      sequence: 5,
      eventType: "task.updated",
      taskId: "t1",
      data: {},
    });
    send(MockWebSocket.instances[0], replayGapEvent({ reason: "since_seq_out_of_window" }));

    expect(onGap).toHaveBeenCalledTimes(1);
    expect(onGap.mock.calls[0][0]).toMatchObject({
      reason: "since_seq_out_of_window",
      currentSequence: 10,
    });
    const internal = stream as unknown as { lastSequence: number | undefined };
    expect(internal.lastSequence).toBeUndefined();
    stream.close();
  });

  it("replay_gap + 随后的 ready 只上报一次缺口（标记被消费）", () => {
    const stream = new TaskEventStream();
    const onGap = vi.fn();
    stream.onReplayGap(onGap);

    stream.connect();
    send(MockWebSocket.instances[0], replayGapEvent());
    send(MockWebSocket.instances[0], readyEvent("ev-new"));

    expect(onGap).toHaveBeenCalledTimes(1);
    stream.close();
  });

  it("system.keepalive / system.ready 不上抛给业务 handler", () => {
    const stream = new TaskEventStream();
    const onEvent = vi.fn();
    stream.onEvent(onEvent);

    stream.connect();
    send(MockWebSocket.instances[0], { eventType: "system.keepalive", data: {} });
    send(MockWebSocket.instances[0], readyEvent("ev-A"));

    expect(onEvent).not.toHaveBeenCalled();
    stream.close();
  });

  it("端点切换：关闭旧 socket 并清空跨订阅游标，保留进程纪元", () => {
    const stream = new TaskEventStream();
    stream.connect();
    send(MockWebSocket.instances[0], readyEvent("ev-A"));
    send(MockWebSocket.instances[0], {
      sequence: 5,
      eventType: "task.updated",
      taskId: "t1",
      data: {},
    });
    const first = MockWebSocket.instances[0];

    // 从全局列表切到任务详情：connect(taskId) 切换端点
    stream.connect("t1");

    expect(first.readyState).toBe(MockWebSocket.CLOSING);
    expect(MockWebSocket.instances).toHaveLength(2);
    const second = MockWebSocket.instances[1];
    const url = new URL(second.url);
    expect(url.pathname).toContain("/ws/tasks/t1");
    // 不复用全局订阅的游标，确保任务端点完整回放自身 history。
    expect(url.searchParams.has("sinceSeq")).toBe(false);
    expect(url.searchParams.get("epoch")).toBe("ev-A");

    stream.close();
  });

  it("同端点重连：保留游标与纪元，携带 sinceSeq 做部分回放", () => {
    const stream = new TaskEventStream();
    stream.connect();
    send(MockWebSocket.instances[0], readyEvent("ev-A"));
    send(MockWebSocket.instances[0], {
      sequence: 42,
      eventType: "task.updated",
      taskId: "t1",
      data: {},
    });
    const internal = stream as unknown as { lastSequence: number | undefined };
    expect(internal.lastSequence).toBe(42);

    // 模拟网络抖动重连（端点不变）：与端点切换相反，游标/纪元均应保留
    stream.close();
    stream.connect();

    const second = MockWebSocket.instances[1];
    const url = new URL(second.url);
    expect(url.pathname).toContain("/ws/tasks");
    expect(url.searchParams.get("sinceSeq")).toBe("42");
    expect(url.searchParams.get("epoch")).toBe("ev-A");
    stream.close();
  });
});

describe("reconnectDelayMs — 指数退避 + jitter", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("attempt 0 落在 [500, 1000]（base=1000 的 50%–100%）", () => {
    for (const r of [0, 0.25, 0.5, 0.75, 1]) {
      vi.spyOn(Math, "random").mockReturnValue(r);
      const delay = reconnectDelayMs(0);
      expect(delay).toBeGreaterThanOrEqual(500);
      expect(delay).toBeLessThanOrEqual(1000);
    }
  });

  it("封顶 15s：attempt 足够大时 jitter 区间上限为 15000", () => {
    vi.spyOn(Math, "random").mockReturnValue(1);
    const delay = reconnectDelayMs(8);
    expect(delay).toBe(15000);
  });

  it("同 attempt 不同 jitter 产生不同延迟（分散重连时刻）", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    const mid = reconnectDelayMs(1); // base=2000 → 1500
    vi.spyOn(Math, "random").mockReturnValue(1);
    const high = reconnectDelayMs(1); // base=2000 → 2000
    expect(mid).not.toBe(high);
  });
});
