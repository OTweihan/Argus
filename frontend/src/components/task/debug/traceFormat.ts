/**
 * LLM trace 展示用纯函数。
 *
 * 抽出来是为了：
 *   - LLMDebugTab（列表）与 TraceDetailPanel（详情）共享同一份 label 映射 / 时间格式，
 *     之前两边各写一份，加新事件 type 容易漏改一处。
 *   - 纯函数可直接 vitest 覆盖，不需要挂在组件实例里。
 */

const EVENT_LABELS: Record<string, string> = {
    "task.llm.started": "started",
    "task.llm.succeeded": "succeeded",
    "task.llm.failed": "failed",
    "task.llm.parse_failed": "parse_failed",
};

export type TraceTagType = "success" | "danger" | "warning" | "info";

const EVENT_TAG_TYPES: Record<string, TraceTagType> = {
    "task.llm.succeeded": "success",
    "task.llm.failed": "danger",
    "task.llm.parse_failed": "warning",
};

export function eventLabel(event: string): string {
    return EVENT_LABELS[event] ?? event;
}

export function eventTagType(event: string): TraceTagType {
    return EVENT_TAG_TYPES[event] ?? "info";
}

const TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
});

export function formatTime(iso: string): string {
    if (!iso) return "-";
    try {
        return TIME_FORMATTER.format(new Date(iso));
    } catch {
        return iso;
    }
}
