import { loadObjectUrl } from "../api";

interface ImageCacheEntry {
  url: string;
  refCount: number;
  lastUsed: number;
}

interface PendingImageFetch {
  promise: Promise<string>;
  controller: AbortController;
  consumers: number;
  settled: boolean;
}

const imageCache = new Map<string, ImageCacheEntry>();
const pendingFetches = new Map<string, PendingImageFetch>();
const CACHE_TTL_MS = 120_000;

function evictStale(): void {
  const now = Date.now();
  for (const [path, entry] of imageCache) {
    if (entry.refCount === 0 && now - entry.lastUsed > CACHE_TTL_MS) {
      imageCache.delete(path);
      URL.revokeObjectURL(entry.url);
    }
  }
}

function waitForImage(promise: Promise<string>, signal: AbortSignal): Promise<string> {
  if (signal.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}

/** 为组件取得一次对 path 的持有；同路径消费者共享底层下载。 */
export async function acquireImage(path: string, signal: AbortSignal): Promise<string> {
  const cached = imageCache.get(path);
  if (cached) {
    cached.refCount += 1;
    cached.lastUsed = Date.now();
    return cached.url;
  }

  let pending = pendingFetches.get(path);
  if (!pending) {
    const controller = new AbortController();
    pending = {
      controller,
      consumers: 0,
      settled: false,
      promise: Promise.resolve(""),
    };
    const entry = pending;
    entry.promise = loadObjectUrl(path, controller.signal).finally(() => {
      entry.settled = true;
      if (pendingFetches.get(path) === entry) pendingFetches.delete(path);
    });
    pendingFetches.set(path, entry);
  }

  pending.consumers += 1;
  try {
    const url = await waitForImage(pending.promise, signal);
    const entry = imageCache.get(path);
    if (entry) {
      entry.refCount += 1;
      entry.lastUsed = Date.now();
      return entry.url;
    }
    imageCache.set(path, { url, refCount: 1, lastUsed: Date.now() });
    evictStale();
    return url;
  } finally {
    pending.consumers = Math.max(0, pending.consumers - 1);
    if (pending.consumers === 0 && !pending.settled) pending.controller.abort();
  }
}

/** 归还一次持有；归零后交由 TTL 惰性回收。 */
export function releaseImage(path: string): void {
  const entry = imageCache.get(path);
  if (!entry) return;
  entry.refCount = Math.max(0, entry.refCount - 1);
  entry.lastUsed = Date.now();
}
