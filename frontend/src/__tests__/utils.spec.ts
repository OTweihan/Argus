import { describe, expect, it } from "vitest";

import {
    canRestartTask,
    canStartTask,
    compact,
    errorCode,
    errorMessage,
    formatDate,
    nullableBoolean,
    nullableNumber,
    nullableText,
    parseJsonObject,
    sortBy,
    taskDisplayStatus,
    upsertById,
} from "../utils";
import { ApiError } from "../api/client";
import type { Task } from "../types";

// 仅给 taskDisplayStatus / canStartTask / canRestartTask 提供它们读取的最小字段集
const dummyTask = (overrides: Partial<Task> = {}): Task =>
    ({
        taskId: overrides.taskId ?? "t-1",
        status: overrides.status ?? "pending",
        schedulerStatus: overrides.schedulerStatus ?? null,
    }) as unknown as Task;

describe("utils.formatDate", () => {
    it("空值返回占位符 -", () => {
        expect(formatDate(null)).toBe("-");
        expect(formatDate("")).toBe("-");
    });

    it("把 ISO 字符串格式化为本地年月日时分秒", () => {
        // 用一个固定时刻，断言只要包含其本地化后的关键片段即可，避开时区差异
        const formatted = formatDate("2026-05-01T12:34:56.000Z");
        expect(formatted).toMatch(/2026-/);
        expect(formatted).toMatch(/:/);
        expect(formatted).toMatch(/\d{2}:\d{2}:\d{2}$/);
    });
});

describe("utils.compact", () => {
    it("超过 length 时按 length-1 截断并加省略号", () => {
        expect(compact("12345", 4)).toBe("123...");
        expect(compact("ab", 5)).toBe("ab");
    });
});

describe("utils.taskDisplayStatus / canStartTask / canRestartTask", () => {
    it("pending + schedulerStatus 优先取 schedulerStatus", () => {
        expect(taskDisplayStatus(dummyTask({ status: "pending", schedulerStatus: "queued" }))).toBe(
            "queued",
        );
    });

    it("pending 且无 schedulerStatus 才能启动", () => {
        expect(canStartTask(dummyTask({ status: "pending" }))).toBe(true);
        expect(canStartTask(dummyTask({ status: "pending", schedulerStatus: "queued" }))).toBe(
            false,
        );
        expect(canStartTask(dummyTask({ status: "running" }))).toBe(false);
    });

    it("只有终态任务可以重试", () => {
        for (const status of ["failed", "timeout", "cancelled"]) {
            expect(canRestartTask(dummyTask({ status: status as Task["status"] }))).toBe(true);
        }
        for (const status of ["pending", "running", "completed"]) {
            expect(canRestartTask(dummyTask({ status: status as Task["status"] }))).toBe(false);
        }
    });
});

describe("utils.nullable*", () => {
    it("nullableText 去空白并把空字符串视为 null", () => {
        expect(nullableText("  hello  ")).toBe("hello");
        expect(nullableText("   ")).toBeNull();
        expect(nullableText("")).toBeNull();
    });

    it("nullableNumber 解析数字、空字符串返回 null、非法值抛错", () => {
        expect(nullableNumber("42", "x")).toBe(42);
        expect(nullableNumber("  ", "x")).toBeNull();
        expect(() => nullableNumber("abc", "字段")).toThrow(/字段/);
    });

    it("nullableBoolean 把字符串映射为布尔 / null", () => {
        expect(nullableBoolean("true")).toBe(true);
        expect(nullableBoolean("false")).toBe(false);
        expect(nullableBoolean("")).toBeNull();
    });
});

describe("utils.parseJsonObject", () => {
    it("空字符串返回空对象", () => {
        expect(parseJsonObject("", "X")).toEqual({});
        expect(parseJsonObject("   ", "X")).toEqual({});
    });

    it("合法 JSON 对象按原样返回", () => {
        expect(parseJsonObject('{"a":1,"b":"c"}', "X")).toEqual({ a: 1, b: "c" });
    });

    it("非法 JSON 抛带 label 的错误", () => {
        expect(() => parseJsonObject("{not json", "参数")).toThrow(/参数/);
    });

    it("数组 / 标量都被拒绝", () => {
        expect(() => parseJsonObject("[1,2]", "X")).toThrow(/JSON 对象/);
        expect(() => parseJsonObject("123", "X")).toThrow(/JSON 对象/);
    });
});

describe("utils.errorMessage / errorCode", () => {
    it("ApiError 带 code 和 message", () => {
        const err = new ApiError("boom", 400, "TASK_NOT_PENDING", { taskId: "x" });
        expect(errorMessage(err)).toBe("boom");
        expect(errorCode(err)).toBe("TASK_NOT_PENDING");
    });

    it("普通 Error 走 message，未知 error 返回兜底文案", () => {
        expect(errorMessage(new Error("oops"))).toBe("oops");
        expect(errorMessage("nothing")).toBe("未知错误。");
        expect(errorCode(new Error("x"))).toBeUndefined();
    });
});

describe("utils.upsertById / sortBy", () => {
    it("upsertById 不存在则插入到头部，存在则就地替换", () => {
        const items = [
            { id: "a", v: 1 },
            { id: "b", v: 2 },
        ];
        const inserted = upsertById(items, { id: "c", v: 3 }, "id");
        expect(inserted.map((x) => x.id)).toEqual(["c", "a", "b"]);

        const replaced = upsertById(items, { id: "b", v: 99 }, "id");
        expect(replaced).toEqual([
            { id: "a", v: 1 },
            { id: "b", v: 99 },
        ]);
    });

    it("sortBy 不修改原数组", () => {
        const original = [{ n: 3 }, { n: 1 }, { n: 2 }];
        const sorted = sortBy(original, (x) => x.n);
        expect(sorted.map((x) => x.n)).toEqual([1, 2, 3]);
        expect(original.map((x) => x.n)).toEqual([3, 1, 2]);
    });
});
