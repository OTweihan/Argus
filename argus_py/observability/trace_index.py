"""LLM trace JSONL 行号偏移索引。

为每个 ``{task_id}.jsonl`` 维护一个 ``{task_id}.idx`` 侧边文件（按行追加），
记录每条 trace 的 ``trace_id`` 及其在 JSONL 中的字节偏移。

**写路径**（``write_trace`` / ``LLMTraceWriter``）在追加 JSONL 后追加索引记录；
**读路径**（``list_llm_traces`` / ``get_llm_trace_detail``）通过索引做随机访问，
避免全量扫描 JSONL。

索引缺失或过时时（写进程被强杀等），首次读取会惰性重建：一次扫描即可构建
完整索引并持久化，避免 JSONL 被扫描两次。
"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TraceIndexEntry = dict[str, Any]
"""``{"trace_id": str, "offset": int}``"""

# ── LRU 缓存 ─────────────────────────────────────────

_TRACE_INDEX_CACHE: OrderedDict[Path, tuple[list[TraceIndexEntry], dict[str, int]]] = OrderedDict()
_TRACE_INDEX_CACHE_MAXSIZE = 128
_TRACE_INDEX_CACHE_LOCK: threading.Lock = threading.Lock()


def _cached_load(trace_path: Path) -> tuple[list[TraceIndexEntry], dict[str, int]] | None:
    """LRU 查询：命中时将条目移至末尾。"""
    key = trace_path.resolve()
    with _TRACE_INDEX_CACHE_LOCK:
        if key in _TRACE_INDEX_CACHE:
            _TRACE_INDEX_CACHE.move_to_end(key)
            return _TRACE_INDEX_CACHE[key]
    return None


def _cache_put(
    trace_path: Path,
    entries: list[TraceIndexEntry],
    offset_map: dict[str, int],
) -> None:
    """LRU 写入并驱逐最旧条目。"""
    key = trace_path.resolve()
    with _TRACE_INDEX_CACHE_LOCK:
        _TRACE_INDEX_CACHE[key] = (entries, offset_map)
        _TRACE_INDEX_CACHE.move_to_end(key)
        while len(_TRACE_INDEX_CACHE) > _TRACE_INDEX_CACHE_MAXSIZE:
            _TRACE_INDEX_CACHE.popitem(last=False)


def _cache_invalidate(trace_path: Path) -> None:
    """追加索引后清除缓存，下次读路径重新加载。"""
    with _TRACE_INDEX_CACHE_LOCK:
        _TRACE_INDEX_CACHE.pop(trace_path.resolve(), None)


def _clear_cache() -> None:
    """清空全部 LRU 缓存。供测试隔离使用，避免跨用例污染。"""
    with _TRACE_INDEX_CACHE_LOCK:
        _TRACE_INDEX_CACHE.clear()


# ── 外部接口 ──────────────────────────────────────────


def append_trace_index(trace_path: Path, trace_id: str, byte_offset: int) -> None:
    """追加一条索引记录到 ``.idx`` 侧边文件。"""
    idx_path = trace_path.with_suffix(".idx")
    try:
        with open(idx_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps({"trace_id": trace_id, "offset": byte_offset}, ensure_ascii=False) + "\n"
            )
    except OSError as exc:
        logger.warning("写入 trace 索引失败：%s err=%s", idx_path, exc)

    _cache_invalidate(trace_path)


def load_trace_index(
    trace_path: Path,
) -> tuple[list[TraceIndexEntry], dict[str, int]]:
    """加载或重建索引。

    缓存优先 → idx 侧边文件 → 全量重建（一次性扫描 JSONL + 后台持久化）。

    Returns:
        (ordered_entries, offset_by_trace_id)
    """
    # 1. LRU 缓存
    cached = _cached_load(trace_path)
    if cached is not None:
        return cached

    # 2. 尝试加载 .idx 侧边文件
    entries = _try_load_idx(trace_path)
    if entries is not None:
        offset_map = _to_offset_map(entries)
        _cache_put(trace_path, entries, offset_map)
        return entries, offset_map

    # 3. 全量重建（一次扫描 JSONL，后台持久化 idx）
    entries = _build_index_from_jsonl(trace_path)
    offset_map = _to_offset_map(entries)
    _cache_put(trace_path, entries, offset_map)
    return entries, offset_map


# ── 内部实现 ──────────────────────────────────────────


def _try_load_idx(trace_path: Path) -> list[TraceIndexEntry] | None:
    """尝试加载已有索引；返回 ``None`` 表示需要重建。"""
    idx_path = trace_path.with_suffix(".idx")
    if not idx_path.exists():
        return None

    entries: list[TraceIndexEntry] = []
    for line in idx_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            entries.append(json.loads(stripped))
        except json.JSONDecodeError:
            return None  # 损坏

    return entries


def _build_index_from_jsonl(trace_path: Path) -> list[TraceIndexEntry]:
    """全量扫描 JSONL 重建索引（一次扫描），后台持久化。"""
    entries: list[TraceIndexEntry] = []
    idx_path = trace_path.with_suffix(".idx")

    try:
        with open(trace_path, encoding="utf-8") as f:
            while True:
                offset = f.tell()
                line = f.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                    trace_id = record.get("trace_id")
                    if trace_id:
                        entries.append({"trace_id": trace_id, "offset": offset})
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []

    if entries:
        _persist_idx_async(idx_path, entries)

    return entries


def _persist_idx_async(idx_path: Path, entries: list[TraceIndexEntry]) -> None:
    """后台持久化重建的索引，不阻塞读路径。"""

    def _write() -> None:
        try:
            idx_path.parent.mkdir(parents=True, exist_ok=True)
            with open(idx_path, "w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("后台持久化 trace 索引失败：%s err=%s", idx_path, exc)

    thread = threading.Thread(target=_write, daemon=True)
    thread.start()


def _to_offset_map(entries: list[TraceIndexEntry]) -> dict[str, int]:
    """转换为 ``{trace_id: offset}`` 映射。"""
    return {e["trace_id"]: e["offset"] for e in entries}
