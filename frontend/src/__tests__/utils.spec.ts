import { describe, expect, it } from "vitest";

import { ApiError } from "../api";
import {
  canRestartTask,
  canStartTask,
  compact,
  displayTaskName,
  errorMessage,
  formatDate,
  httpMethodTag,
  nullableBoolean,
  nullableText,
  overloadMessage,
  sortBy,
  taskDisplayStatus,
  upsertById,
} from "../utils";
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
    expect(canStartTask(dummyTask({ status: "pending", schedulerStatus: "queued" }))).toBe(false);
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

  it("nullableBoolean 把字符串映射为布尔 / null", () => {
    expect(nullableBoolean("true")).toBe(true);
    expect(nullableBoolean("false")).toBe(false);
    expect(nullableBoolean("")).toBeNull();
  });
});

describe("utils.errorMessage", () => {
  it("普通 Error 走 message，未知 error 返回兜底文案", () => {
    expect(errorMessage(new Error("oops"))).toBe("oops");
    expect(errorMessage("nothing")).toBe("未知错误。");
  });
});

describe("utils.overloadMessage", () => {
  it("TASK_QUEUE_FULL / RATE_LIMITED / 429 / 503 显示稍后重试提示", () => {
    const retry = "系统繁忙：任务队列已满，请稍后重试。";
    expect(overloadMessage(new ApiError("x", 503, "TASK_QUEUE_FULL"))).toBe(retry);
    expect(overloadMessage(new ApiError("x", 429, "RATE_LIMITED"))).toBe(retry);
    expect(overloadMessage(new ApiError("x", 503))).toBe(retry);
    expect(overloadMessage(new ApiError("x", 429))).toBe(retry);
  });

  it("非过载错误回退到 errorMessage", () => {
    expect(overloadMessage(new ApiError("普通业务错误", 400, "TASK_ERROR"))).toBe("普通业务错误");
    expect(overloadMessage(new Error("oops"))).toBe("oops");
    expect(overloadMessage("nothing")).toBe("未知错误。");
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

describe("utils.httpMethodTag", () => {
  it("GET → success", () => {
    expect(httpMethodTag("GET")).toBe("success");
    expect(httpMethodTag("get")).toBe("success");
  });

  it("POST → primary", () => {
    expect(httpMethodTag("POST")).toBe("primary");
  });

  it("PUT / PATCH → warning", () => {
    expect(httpMethodTag("PUT")).toBe("warning");
    expect(httpMethodTag("PATCH")).toBe("warning");
  });

  it("DELETE → danger", () => {
    expect(httpMethodTag("DELETE")).toBe("danger");
  });

  it("unknown → info", () => {
    expect(httpMethodTag("OPTIONS")).toBe("info");
    expect(httpMethodTag("")).toBe("info");
  });
});

describe("utils.displayTaskName", () => {
  it("有 name 时展示「名称（第N次）」", () => {
    expect(displayTaskName({ name: "登录测试", executionAttempt: 2 })).toBe("登录测试（第2次）");
    expect(displayTaskName({ name: "登录测试", executionAttempt: 1 })).toBe("登录测试（第1次）");
  });

  it("name 为空回退为 -（不带次数）", () => {
    expect(displayTaskName({ name: null, executionAttempt: 1 })).toBe("-");
    expect(displayTaskName({ name: "", executionAttempt: 3 })).toBe("-");
  });

  it("executionAttempt 缺失时按第 1 次兜底", () => {
    expect(displayTaskName({ name: "登录测试" })).toBe("登录测试（第1次）");
  });
});
