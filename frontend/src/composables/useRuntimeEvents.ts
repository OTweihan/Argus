import { computed, onUnmounted, ref, type Ref } from "vue";

import type { TaskEvent } from "../types";
import { TaskEventStream } from "../ws";
import type { ViewKey } from "./useNavigation";

type EventStatus = "connected" | "disconnected" | "error";

export function useRuntimeEvents() {
    const eventStream = new TaskEventStream();
    const eventStatus = ref<EventStatus>("disconnected");

    const eventStatusText = computed(() => {
        return eventStatus.value === "connected"
            ? "已连接"
            : eventStatus.value === "error"
                ? "异常"
                : "未连接";
    });

    eventStream.onStatus((nextStatus) => {
        eventStatus.value = nextStatus;
    });

    const taskEventCallbacks: ((event: TaskEvent) => void)[] = [];

    eventStream.onEvent((event) => {
        const eventType = event.eventType ?? event.type ?? "";
        if (!eventType.startsWith("task.")) return;
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

    return { eventStatus, eventStatusText, onTaskEvent, connectEventStream };
}
