"""LLM trace 后台批量 writer 与启动期清理。

设计目标
========
1. 把磁盘 IO 从 LLM 调用热路径中剥离：调用方调用 ``LLMTraceWriter.enqueue`` 仅做
   一次 ``queue.put_nowait``，开销恒定且不会阻塞事件循环或 LLM 协程。
2. 单 daemon 线程按文件路径分桶批量 append，避免每条 trace 都 open/close 文件。
3. 队列满时 fail-fast：丢弃最新条目并累计计数，调用方拿到 ``False`` 决定是否
   降级（例如改为本进程 logger.warning）。这样比阻塞调用方更安全。
4. 优雅停机：``stop`` 会发送哨兵并 join，确保 process exit 前队列内残留写入磁盘。
5. 启动期清理：``cleanup_old_traces`` 按 mtime 做 TTL 删除 + 按总量裁剪，防止
   长期跑下来 ``outputs/traces`` 无限膨胀。
"""

from __future__ import annotations

import json as _json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SENTINEL = object()
# 单文件批量 flush 阈值：满 32 条立即落盘，缩短崩溃时丢失窗口。
_BATCH_FLUSH_THRESHOLD = 32
# 默认空闲 flush 间隔（秒）：保证低 QPS 下也能及时落盘。
_DEFAULT_FLUSH_INTERVAL_SECONDS = 0.5


class LLMTraceWriter:
    """全局 LLM trace 后台批量 writer。

    线程安全：``enqueue`` 可在任意线程或协程中无锁调用（``queue.Queue`` 自带互斥）；
    ``start`` / ``stop`` 用 ``threading.Lock`` 保护避免重复启停。
    """

    def __init__(
        self,
        max_queue_size: int = 10000,
        flush_interval_seconds: float = _DEFAULT_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max_queue_size)
        self._thread: threading.Thread | None = None
        self._running = False
        self._flush_interval = flush_interval_seconds
        self._lock = threading.Lock()
        # 监控指标：调用方可读取这两个数字判断是否过载。
        self.dropped_count = 0
        self.written_count = 0

    # ── 生命周期 ──────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run, name="llm-trace-writer", daemon=True)
            self._thread.start()
        logger.debug("LLMTraceWriter started")

    def stop(self, timeout: float = 5.0) -> None:
        """优雅停机：投递哨兵触发 flush，并 join 后台线程。

        ``timeout`` 控制 join 最长等待秒数；超时则放弃等待（daemon 线程会随主
        进程退出），不阻塞 server shutdown。
        """
        with self._lock:
            if not self._running:
                return
            self._running = False
        try:
            self._queue.put((_SENTINEL, ""), timeout=1.0)
        except queue.Full:
            # 队列已满时强行 put_nowait 会丢哨兵；退而求其次：直接 join，
            # worker 会在下一轮 flush 周期看到 _running=False 主动退出。
            logger.warning("LLMTraceWriter queue is full at shutdown; will rely on flush loop")
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.debug(
            "LLMTraceWriter stopped: written=%d, dropped=%d",
            self.written_count,
            self.dropped_count,
        )

    # ── 投递 ──────────────────────────────────────

    def enqueue(self, file_path: Path, record: Any) -> bool:
        """非阻塞投递一条待处理的 trace 记录。

        ``record`` 在 writer 线程中执行 asdict / 脱敏 / 序列化，不阻塞事件循环。
        队列满时返回 ``False``（不抛异常），调用方可降级为本地写入。
        """
        try:
            self._queue.put_nowait((file_path, record))
            return True
        except queue.Full:
            self.dropped_count += 1
            # 这里只在累计每 100 条时告警一次，避免日志风暴。
            if self.dropped_count % 100 == 1:
                logger.warning(
                    "LLMTraceWriter queue full, dropped %d records so far",
                    self.dropped_count,
                )
            return False

    # ── 内部 worker ──────────────────────────────────────

    def _run(self) -> None:
        """后台线程主循环：聚合 buffer，定时或按阈值 flush。"""
        buffer: dict[Path, list[Any]] = {}
        while True:
            try:
                item = self._queue.get(timeout=self._flush_interval)
            except queue.Empty:
                # 空闲 tick：把累计 buffer 落盘，并检查是否被通知停机。
                if buffer:
                    self._flush_all(buffer)
                if not self._running:
                    break
                continue

            path_obj, record = item
            if path_obj is _SENTINEL:
                # 停机哨兵：把剩余 buffer flush 完再退出。
                if buffer:
                    self._flush_all(buffer)
                break

            assert isinstance(path_obj, Path)
            bucket = buffer.setdefault(path_obj, [])
            bucket.append(record)
            if len(bucket) >= _BATCH_FLUSH_THRESHOLD:
                # 单文件阈值满了直接 flush 单 bucket，其它文件继续累积。
                self._flush_file(path_obj, buffer.pop(path_obj))

    def _flush_all(self, buffer: dict[Path, list[Any]]) -> None:
        for path, records in list(buffer.items()):
            self._flush_file(path, records)
        buffer.clear()

    def _flush_file(self, path: Path, records: list[Any]) -> None:
        """在 writer 线程中处理一批 trace 记录：stat / asdict / 脱敏 / 序列化 -> 落盘。"""
        if not records:
            return
        # 延迟导入避免与 llm_trace 的循环依赖
        from dataclasses import asdict

        from argus_py.observability.llm_trace import (
            _LLM_TRACE_CONTENT_REDACT,
            _LLM_TRACE_MAX_SIZE_BYTES,
            _ensure_config,
            redact_trace_data,
        )

        _ensure_config()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            idx_path = path.with_suffix(".idx")
            idx_entries: list[tuple[str, int]] = []
            with open(path, "a", encoding="utf-8") as f:
                for record in records:
                    # 大小上限检查（stat 已在后台线程，不阻塞 event loop）
                    if (
                        _LLM_TRACE_MAX_SIZE_BYTES is not None
                        and _LLM_TRACE_MAX_SIZE_BYTES > 0
                        and path.exists()
                        and path.stat().st_size >= _LLM_TRACE_MAX_SIZE_BYTES
                    ):
                        logger.warning(
                            "LLM 追踪文件超出大小上限 (%d MB)，跳过写入：%s",
                            _LLM_TRACE_MAX_SIZE_BYTES // (1024 * 1024),
                            path,
                        )
                        continue
                    data = asdict(record)
                    if _LLM_TRACE_CONTENT_REDACT:
                        data = redact_trace_data(data)
                    line = _json.dumps(data, ensure_ascii=False, default=str)
                    offset = f.tell()
                    f.write(line + "\n")
                    tid = data.get("trace_id", "")
                    if tid:
                        idx_entries.append((tid, offset))
            if idx_entries:
                with open(idx_path, "a", encoding="utf-8") as f_idx:
                    for tid, offset in idx_entries:
                        f_idx.write(
                            _json.dumps({"trace_id": tid, "offset": offset}, ensure_ascii=False)
                            + "\n"
                        )
            self.written_count += len(records)
        except OSError as exc:
            logger.warning(
                "LLM trace flush failed: path=%s err=%s, dropped %d records",
                path,
                exc,
                len(records),
            )


# ── 全局单例 ──────────────────────────────────────


_global_writer: LLMTraceWriter | None = None
_global_lock = threading.Lock()


def get_trace_writer() -> LLMTraceWriter | None:
    """返回已启动的 writer，未启动时返回 ``None``。

    返回 ``None`` 表示同步 fallback 模式（测试/CLI 或显式禁用）。
    """
    return _global_writer


def start_trace_writer(max_queue_size: int = 10000) -> LLMTraceWriter:
    """启动全局 writer（幂等）。返回 writer 实例供调用方直接 enqueue。"""
    global _global_writer
    with _global_lock:
        if _global_writer is None:
            _global_writer = LLMTraceWriter(max_queue_size=max_queue_size)
            _global_writer.start()
        return _global_writer


def stop_trace_writer(timeout: float = 5.0) -> None:
    """停止全局 writer 并 flush 剩余记录。"""
    global _global_writer
    with _global_lock:
        if _global_writer is None:
            return
        _global_writer.stop(timeout=timeout)
        _global_writer = None


# ── 启动期清理 ──────────────────────────────────────


def cleanup_old_traces(
    traces_dir: Path,
    retention_days: int,
    total_size_mb: int,
) -> dict[str, int]:
    """启动期 trace 目录清理：TTL 删除 + 总量裁剪。

    返回 ``{"deleted_ttl": int, "deleted_quota": int, "remaining_files": int,
    "remaining_size_mb": int}``，便于上游 audit。

    清理顺序：
    1. TTL：``mtime`` 早于 ``retention_days`` 之前的文件直接删。``retention_days``
       <= 0 时跳过该阶段。
    2. 总量裁剪：剩余文件按 ``mtime`` 升序删除，直到总大小 <= ``total_size_mb``。
       ``total_size_mb`` <= 0 时跳过该阶段。

    任一阶段对单个文件的 ``unlink`` 失败（被打开 / 权限不足）只 warn 并跳过，
    不中断清理流程。
    """
    deleted_ttl = 0
    deleted_quota = 0
    if not traces_dir.exists():
        return {
            "deleted_ttl": 0,
            "deleted_quota": 0,
            "remaining_files": 0,
            "remaining_size_mb": 0,
        }

    files = [p for p in traces_dir.glob("*.jsonl") if p.is_file()]

    # Step 1: TTL
    if retention_days > 0:
        cutoff = time.time() - retention_days * 86400
        survivors: list[Path] = []
        for f in files:
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                try:
                    f.unlink()
                except OSError as exc:
                    logger.warning("trace TTL 清理失败：%s err=%s", f, exc)
                    survivors.append(f)
                    continue
                try:
                    f.with_suffix(".idx").unlink(missing_ok=True)
                except OSError:
                    pass
                deleted_ttl += 1
            else:
                survivors.append(f)
        files = survivors

    # Step 2: 总量裁剪（按 mtime 升序删旧的）
    if total_size_mb > 0:
        budget = total_size_mb * 1024 * 1024
        entries: list[tuple[Path, float, int, int]] = []
        for f in files:
            try:
                st = f.stat()
                idx_path = f.with_suffix(".idx")
                idx_size = idx_path.stat().st_size if idx_path.is_file() else 0
                entries.append((f, st.st_mtime, st.st_size, idx_size))
            except OSError:
                continue
        entries.sort(key=lambda x: x[1])
        total_size = sum(size + idx_size for _, _, size, idx_size in entries)
        idx = 0
        while total_size > budget and idx < len(entries):
            path, _, size, idx_size = entries[idx]
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("trace 总量清理失败：%s err=%s", path, exc)
                idx += 1
                continue
            try:
                path.with_suffix(".idx").unlink(missing_ok=True)
            except OSError:
                pass
            total_size -= size + idx_size
            deleted_quota += 1
            idx += 1
        files = [path for path, _, _, _ in entries[idx:]]

    remaining_size = 0
    for f in files:
        try:
            remaining_size += f.stat().st_size
            idx_path = f.with_suffix(".idx")
            if idx_path.is_file():
                remaining_size += idx_path.stat().st_size
        except OSError:
            continue
    summary = {
        "deleted_ttl": deleted_ttl,
        "deleted_quota": deleted_quota,
        "remaining_files": len(files),
        "remaining_size_mb": remaining_size // (1024 * 1024),
    }
    if deleted_ttl or deleted_quota:
        logger.info(
            "LLM trace 启动清理：ttl=%d, quota=%d, remaining_files=%d, remaining_mb=%d",
            deleted_ttl,
            deleted_quota,
            summary["remaining_files"],
            summary["remaining_size_mb"],
        )
    return summary
