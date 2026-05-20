import { computed, onUnmounted, ref, type Ref } from "vue";

import type { TaskEvent } from "../types";
import { TaskEventStream } from "../ws";
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

    onUnmounted(() => {
        eventStream.close();
    });

    return { eventStatus, eventStatusText, onTaskEvent, onReconnect, connectEventStream };
}
