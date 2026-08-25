import { getCurrentScope, onScopeDispose, ref, type Ref } from "vue";
import { errorMessage } from "../utils";

/**
 * 通用分页列表 composable，收敛白盒报告 / 关联证据里反复复制的
 * load / loadMore / cursor / total / hasMore / loading 样板。
 *
 * 同时修复两处既有问题：
 *   - 旧实现 load / loadMore 只有 try/finally 没有 catch，分页失败会抛未处理
 *     rejection；这里内置 catch 写入 per-list error ref（可选 onError 上抛）。
 *   - 旧实现切 run 时可能让过期响应覆盖新数据；这里用 requestSeq 代际守卫丢弃
 *     过期响应。
 */

export interface PagedResult<T> {
  items: T[];
  total?: number | null;
  hasMore: boolean;
  nextCursor?: string | null;
}

export interface PagedListOptions {
  /** 每页大小，默认 50。 */
  limit?: number;
  /** true = cursor 分页（nextCursor 驱动，如白盒子资源）；默认 offset 分页。 */
  cursor?: boolean;
  /** 可选：错误上抛回调（如转成全局提示）。子列表通常不传，失败静默但被 error ref 跟踪。 */
  onError?: (msg: string) => void;
  /** true = 仅首次成功加载后跳过后续 load()（如未触达端点"懒加载一次"语义）。 */
  lazyOnce?: boolean;
}

/** 传给 fetcher 的分页请求描述。signal 由本 composable 管理： */
export interface PageRequest {
  /** offset 分页的起始下标（首页 / cursor 分页恒为 0）。 */
  offset: number;
  cursor: string | null;
  limit: number;
  /**
   * 本次请求的中止信号（可选）。接入底层 request 后可真正取消在途请求：
   * 新 load / reset / 卸载会 abort 旧信号；不关心取消的 fetcher 忽略即可。
   */
  signal?: AbortSignal;
}

export interface PagedList<T, A extends unknown[]> {
  items: Ref<T[]>;
  total: Ref<number | null>;
  hasMore: Ref<boolean>;
  loading: Ref<boolean>;
  error: Ref<string>;
  /** 首页：重置到第一页。 */
  load: (...args: A) => Promise<void>;
  /** 下一页：按 offset（offset 分页）或 nextCursor（cursor 分页）追加。 */
  loadMore: (...args: A) => Promise<void>;
  /** 清空并让在途请求失效（切 run / 切筛选条件时调用）。 */
  reset: () => void;
}

export function usePagedList<T, A extends unknown[]>(
  fetcher: (
    pagination: PageRequest,
    ...args: A
  ) => Promise<PagedResult<T>>,
  options: PagedListOptions = {},
): PagedList<T, A> {
  const items = ref<T[]>([]) as Ref<T[]>;
  const total = ref<number | null>(null);
  const hasMore = ref(false);
  const loading = ref(false);
  const error = ref("");
  const limit = options.limit ?? 50;
  let cursor: string | null = null;
  let requestSeq = 0;
  let disposed = false;
  let activeController: AbortController | null = null;

  // 组件卸载 / 切 run 后丢弃后续写入：requestSeq 只防乱序，不防卸载后写死 ref。
  // 需在 Vue effect scope（组件 setup / effectScope）内调用；纯函数调用场景跳过注册，
  // 避免无活跃 scope 时抛错（与 useTaskList 一致）。
  if (getCurrentScope()) {
    onScopeDispose(() => {
      disposed = true;
      requestSeq += 1;
      activeController?.abort();
      activeController = null;
    });
  }

  /** 开启一次新请求：作废上一个在途请求并返回其控制器。 */
  function beginRequest(): { seq: number; controller: AbortController } {
    activeController?.abort();
    const controller = new AbortController();
    activeController = controller;
    return { seq: ++requestSeq, controller };
  }

  function handleError(caught: unknown): void {
    error.value = errorMessage(caught);
    options.onError?.(error.value);
  }

  async function load(...args: A): Promise<void> {
    if (options.lazyOnce && items.value.length > 0) return;
    if (disposed) return;
    const { seq, controller } = beginRequest();
    error.value = "";
    loading.value = true;
    try {
      const page = await fetcher(
        { offset: 0, cursor: null, limit, signal: controller.signal },
        ...args,
      );
      if (seq !== requestSeq || disposed) return; // 已有更新的 load/reset/卸载，丢弃过期响应
      items.value = page.items;
      total.value = page.total ?? null;
      hasMore.value = page.hasMore;
      cursor = page.nextCursor ?? null;
    } catch (caught) {
      // 被主动取消的请求必然伴随 seq 失效/卸载，静默丢弃而非写错误
      if (seq !== requestSeq || disposed || controller.signal.aborted) return;
      handleError(caught);
    } finally {
      if (seq === requestSeq && !disposed) loading.value = false;
    }
  }

  async function loadMore(...args: A): Promise<void> {
    if (loading.value || !hasMore.value || disposed) return;
    if (options.cursor && cursor === null) return; // cursor 分页下无下一页
    const { seq, controller } = beginRequest();
    const offset = items.value.length;
    loading.value = true;
    try {
      const page = await fetcher(
        options.cursor
          ? { offset: 0, cursor, limit, signal: controller.signal }
          : { offset, cursor: null, limit, signal: controller.signal },
        ...args,
      );
      if (seq !== requestSeq || disposed) return;
      items.value = items.value.concat(page.items);
      hasMore.value = page.hasMore;
      cursor = page.nextCursor ?? null;
    } catch (caught) {
      if (seq !== requestSeq || disposed || controller.signal.aborted) return;
      handleError(caught);
    } finally {
      if (seq === requestSeq && !disposed) loading.value = false;
    }
  }

  function reset(): void {
    activeController?.abort();
    activeController = null;
    requestSeq += 1;
    items.value = [];
    total.value = null;
    hasMore.value = false;
    loading.value = false;
    error.value = "";
    cursor = null;
  }

  return { items, total, hasMore, loading, error, load, loadMore, reset };
}
