import { describe, expect, it, vi } from "vitest";
import { usePagedList, type PagedResult, type PageRequest } from "../usePagedList";

/** 构造一个可控的 fetcher：每次调用记录参数，并按 entries 顺序返回 resolve/reject。 */
function makeDeferredFetcher<T>() {
  const entries: {
    args: unknown[];
    pagination: PageRequest;
    resolve: (value: PagedResult<T>) => void;
    reject: (err: unknown) => void;
  }[] = [];

  const fetcher = vi.fn(
    (
      pagination: PageRequest,
      ...args: unknown[]
    ) =>
      new Promise<PagedResult<T>>((res, rej) => {
        entries.push({ args, pagination, resolve: res, reject: rej });
      }),
  );

  return { fetcher, entries };
}

function page<T>(items: T[], extra: Partial<PagedResult<T>> = {}): PagedResult<T> {
  return { items, hasMore: false, total: items.length, ...extra };
}

async function flush(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("usePagedList", () => {
  it("load 首页写入 items/total/hasMore 并复位 cursor", async () => {
    const { fetcher, entries } = makeDeferredFetcher<number>();
    const list = usePagedList<number, [string]>(fetcher, { limit: 10 });

    const pending = list.load("a");
    await flush();
    entries[0].resolve(page([1, 2, 3], { hasMore: true, nextCursor: "c1" }));
    await pending;

    expect(list.items.value).toEqual([1, 2, 3]);
    expect(list.total.value).toBe(3);
    expect(list.hasMore.value).toBe(true);
    // signal 为每次请求独立生成，断言用子集匹配
    expect(entries[0].pagination).toMatchObject({ offset: 0, cursor: null, limit: 10 });
  });

  it("loadMore offset 分页按当前 items 长度作为 offset 追加", async () => {
    const { fetcher, entries } = makeDeferredFetcher<number>();
    const list = usePagedList<number, []>(fetcher, { limit: 2 });

    const first = list.load();
    await flush();
    entries[0].resolve(page([1, 2], { hasMore: true }));
    await first;

    const second = list.loadMore();
    await flush();
    expect(entries[1].pagination).toMatchObject({ offset: 2, cursor: null, limit: 2 });
    entries[1].resolve(page([3, 4], { hasMore: false }));
    await second;

    expect(list.items.value).toEqual([1, 2, 3, 4]);
    expect(list.hasMore.value).toBe(false);
  });

  it("loadMore cursor 分页传递 nextCursor 而非 offset", async () => {
    const { fetcher, entries } = makeDeferredFetcher<number>();
    const list = usePagedList<number, []>(fetcher, { cursor: true, limit: 2 });

    const first = list.load();
    await flush();
    entries[0].resolve(page([1, 2], { hasMore: true, nextCursor: "c1" }));
    await first;

    const second = list.loadMore();
    await flush();
    expect(entries[1].pagination).toMatchObject({ offset: 0, cursor: "c1", limit: 2 });
    entries[1].resolve(page([3], { hasMore: false, nextCursor: null }));
    await second;
    expect(list.items.value).toEqual([1, 2, 3]);
  });

  it("每次请求携带独立 signal，新 load/reset 中止旧请求", async () => {
    const { fetcher, entries } = makeDeferredFetcher<number>();
    const list = usePagedList<number, [string]>(fetcher);

    // 两次 load 均不 resolve：验证的是在途请求的 signal 状态
    list.load("a");
    await flush();
    expect(entries[0].pagination.signal).toBeInstanceOf(AbortSignal);
    expect(entries[0].pagination.signal?.aborted).toBe(false);

    // 新 load 作废旧在途请求：旧 signal 被真正 abort
    list.load("b");
    await flush();
    expect(entries[0].pagination.signal?.aborted).toBe(true);
    expect(entries[1].pagination.signal?.aborted).toBe(false);

    // reset 同样中止在途请求
    list.reset();
    expect(entries[1].pagination.signal?.aborted).toBe(true);
  });

  it("代际守卫：迟到的旧 load 响应不覆盖新 load", async () => {
    const { fetcher, entries } = makeDeferredFetcher<number>();
    const list = usePagedList<number, [string]>(fetcher);

    const first = list.load("old");
    const second = list.load("new");
    await flush();

    // 新响应先返回，旧响应后返回
    entries[1].resolve(page([9]));
    await second;
    entries[0].resolve(page([1, 2, 3]));
    await first;

    expect(list.items.value).toEqual([9]);
  });

  it("reset 清空状态并使在途响应失效", async () => {
    const { fetcher, entries } = makeDeferredFetcher<number>();
    const list = usePagedList<number, [string]>(fetcher);

    const first = list.load("a");
    await flush();
    list.reset();
    entries[0].resolve(page([1, 2, 3]));
    await first;

    expect(list.items.value).toEqual([]);
    expect(list.total.value).toBeNull();
    expect(list.hasMore.value).toBe(false);
    expect(list.loading.value).toBe(false);
  });

  it("lazyOnce 已加载后跳过后续 load", async () => {
    const { fetcher, entries } = makeDeferredFetcher<number>();
    const list = usePagedList<number, [string]>(fetcher, { lazyOnce: true });

    const first = list.load("a");
    await flush();
    entries[0].resolve(page([1]));
    await first;

    await list.load("b");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(list.items.value).toEqual([1]);
  });

  it("load 失败写入 error 且不改变已有 items", async () => {
    const { fetcher, entries } = makeDeferredFetcher<number>();
    const list = usePagedList<number, [string]>(fetcher);

    const first = list.load("a");
    await flush();
    entries[0].resolve(page([1]));
    await first;

    const second = list.load("b");
    await flush();
    entries[1].reject(new Error("boom"));
    await second;

    expect(list.error.value).toContain("boom");
    expect(list.items.value).toEqual([1]);
  });
});
