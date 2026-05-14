import { effectScope } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebounceFn } from "../useDebounceFn";

describe("useDebounceFn", () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("延迟 delayMs 后才真正执行 fn", () => {
        const fn = vi.fn();
        const debounced = useDebounceFn(fn, 200);

        debounced();
        expect(fn).not.toHaveBeenCalled();

        vi.advanceTimersByTime(199);
        expect(fn).not.toHaveBeenCalled();

        vi.advanceTimersByTime(1);
        expect(fn).toHaveBeenCalledTimes(1);
    });

    it("等待期内多次触发只会合并为最后一次执行（最后一次的参数）", () => {
        const fn = vi.fn();
        const debounced = useDebounceFn(fn, 200);

        debounced("a");
        vi.advanceTimersByTime(100);
        debounced("b");
        vi.advanceTimersByTime(100);
        debounced("c");

        // 此时距最后一次调用还差 100ms，fn 不应被触发
        expect(fn).not.toHaveBeenCalled();
        vi.advanceTimersByTime(199);
        expect(fn).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(fn).toHaveBeenCalledTimes(1);
        expect(fn).toHaveBeenCalledWith("c");
    });

    it("cancel() 丢弃 pending 调用", () => {
        const fn = vi.fn();
        const debounced = useDebounceFn(fn, 200);

        debounced();
        debounced.cancel();

        vi.advanceTimersByTime(500);
        expect(fn).not.toHaveBeenCalled();
    });

    it("flush() 立即触发 pending 调用", () => {
        const fn = vi.fn();
        const debounced = useDebounceFn(fn, 200);

        debounced("only");
        debounced.flush();
        expect(fn).toHaveBeenCalledTimes(1);
        expect(fn).toHaveBeenCalledWith("only");

        // flush 后没有 pending 时再调一次 flush 应是 no-op
        debounced.flush();
        expect(fn).toHaveBeenCalledTimes(1);
    });

    it("挂在 effectScope 上：scope.stop() 自动 cancel pending 调用", () => {
        const fn = vi.fn();
        const scope = effectScope();
        scope.run(() => {
            const debounced = useDebounceFn(fn, 200);
            debounced();
        });

        scope.stop();
        vi.advanceTimersByTime(500);
        expect(fn).not.toHaveBeenCalled();
    });
});
