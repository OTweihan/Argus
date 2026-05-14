import { getCurrentScope, onScopeDispose } from "vue";

/**
 * 通用防抖 helper：把一组高频触发的回调合并成最后一次调用。
 *
 * - 返回的函数（debounced）在每次调用时重置等待计时器；只有在 `delayMs`
 *   毫秒内不再被调用时，才真正执行 `fn`。
 * - 自动绑定 Vue 当前 effect scope：在组件卸载（或 setup scope 销毁）时
 *   自动 `cancel`，避免持有已销毁组件的闭包。
 * - 额外暴露 `cancel()` / `flush()`：分别用于丢弃 pending 调用、立即触发
 *   pending 调用。
 *
 * 使用示例：
 *   const debouncedSearch = useDebounceFn(() => loadList(), 300);
 *   watch(query, debouncedSearch);
 */
export interface DebouncedFn<TArgs extends unknown[]> {
    (...args: TArgs): void;
    cancel(): void;
    flush(): void;
}

export function useDebounceFn<TArgs extends unknown[]>(
    fn: (...args: TArgs) => void | Promise<void>,
    delayMs: number,
): DebouncedFn<TArgs> {
    let timer: number | null = null;
    let pendingArgs: TArgs | null = null;

    function cancel(): void {
        if (timer !== null) {
            window.clearTimeout(timer);
            timer = null;
        }
        pendingArgs = null;
    }

    function run(): void {
        const args = pendingArgs;
        timer = null;
        pendingArgs = null;
        if (args) void fn(...args);
    }

    function flush(): void {
        if (timer !== null && pendingArgs !== null) {
            window.clearTimeout(timer);
            run();
        }
    }

    function debounced(...args: TArgs): void {
        if (timer !== null) window.clearTimeout(timer);
        pendingArgs = args;
        timer = window.setTimeout(run, delayMs);
    }

    // 在 Vue setup / 任意 effect scope 内自动卸载清理；纯函数调用场景需手动 cancel。
    if (getCurrentScope()) {
        onScopeDispose(cancel);
    }

    return Object.assign(debounced as DebouncedFn<TArgs>, { cancel, flush });
}
