import { computed, nextTick, onUnmounted, ref, watch, type Ref } from "vue";

import type { TaskEvent } from "../types";
import { TaskEventStream, type ReplayGapInfo } from "../ws";
import type { ViewKey } from "./useNavigation";

type EventStatus = "connected" | "disconnected" | "error" | "reconnecting" | "reconnected";

export function useRuntimeEvents() {
  const eventStream = new TaskEventStream();
  const eventStatus = ref<EventStatus>("disconnected");

  const eventStatusText = computed(() => {
    return eventStatus.value === "connected" || eventStatus.value === "reconnected"
      ? "已连接"
      : eventStatus.value === "error"
        ? "异常"
        : eventStatus.value === "reconnecting"
          ? "重连中"
          : "未连接";
  });

  eventStream.onStatus((nextStatus) => {
    eventStatus.value = nextStatus;
  });

  /* ── 重连同步 ── */

  const reconnectCallbacks: (() => void)[] = [];

  function onReconnect(callback: () => void): () => void {
    reconnectCallbacks.push(callback);
    return () => {
      const idx = reconnectCallbacks.indexOf(callback);
      if (idx !== -1) reconnectCallbacks.splice(idx, 1);
    };
  }

  eventStream.onStatus((status) => {
    if (status === "reconnected") {
      for (const cb of reconnectCallbacks) cb();
    }
  });

  /* ── 回放缺口同步 ── */

  const replayGapCallbacks: ((info: ReplayGapInfo) => void)[] = [];

  /** 服务端判定回放存在缺口（sinceSeq 超窗 / 服务重启 epoch 变化）时触发，
   * 上层应丢弃旧游标并从权威接口重建列表、当前任务与时间线。 */
  function onReplayGap(callback: (info: ReplayGapInfo) => void): () => void {
    replayGapCallbacks.push(callback);
    return () => {
      const idx = replayGapCallbacks.indexOf(callback);
      if (idx !== -1) replayGapCallbacks.splice(idx, 1);
    };
  }

  eventStream.onReplayGap((info) => {
    for (const cb of replayGapCallbacks) cb(info);
  });

  /* ── 事件分发 ── */

  const taskEventCallbacks: ((event: TaskEvent) => void)[] = [];

  eventStream.onEvent((event) => {
    if (!event.eventType.startsWith("task.")) return;
    for (const cb of taskEventCallbacks) cb(event);
  });

  function onTaskEvent(callback: (event: TaskEvent) => void): () => void {
    taskEventCallbacks.push(callback);
    return () => {
      const idx = taskEventCallbacks.indexOf(callback);
      if (idx !== -1) taskEventCallbacks.splice(idx, 1);
    };
  }

  function connectEventStream(view: Ref<ViewKey>, selectedTaskId: Ref<string | null>): void {
    if (view.value === "task-detail" && selectedTaskId.value) {
      eventStream.connect(selectedTaskId.value);
    } else {
      eventStream.connect();
    }
  }

  /** 视图 / 选中任务变化时自动重连事件流。
   *
   * 之前 `useTaskSelection.selectTask` 主动回调 `connectEventStream`，而闭包又需要
   * `selectedTaskId`，形成"鸡生蛋"。现在反向：状态层只更新状态，这里 watch
   * `[view, selectedTaskId]` 任一变化都触发重连，Vue 批量更新机制保证两者同
   * tick 变化时只触发一次。
   */
  function watchEventStream(view: Ref<ViewKey>, selectedTaskId: Ref<string | null>): void {
    watch([view, selectedTaskId], () => {
      // nextTick 确保视图切换渲染完成后再重连 WebSocket，
      // 避免 event replay 触发 allTasks 更新导致 el-table 闪烁。
      nextTick(() => connectEventStream(view, selectedTaskId));
    });
  }

  onUnmounted(() => {
    eventStream.close();
  });

  return {
    eventStatus,
    eventStatusText,
    onTaskEvent,
    onReconnect,
    onReplayGap,
    connectEventStream,
    watchEventStream,
  };
}
