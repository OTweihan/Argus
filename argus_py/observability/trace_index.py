"""LLM trace JSONL 行号偏移索引。

为每个 ``{task_id}.jsonl`` 维护一个 ``{task_id}.idx`` 侧边文件（按行追加），
记录每条 trace 的 ``trace_id`` 及其在 JSONL 中的字节偏移。

**写路径**（``write_trace`` / ``LLMTraceWriter``）在追加 JSONL 后追加索引记录；
**读路径**（``list_llm_traces`` / ``get_llm_trace_detail``）通过索引做随机访问，
避免全量扫描 JSONL。

索引缺失或过时时（写进程被强杀等），首次读取会惰性重建。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


TraceIndexEntry = dict[str, Any]
"""``{"trace_id": str, "offset": int}``"""


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


def load_trace_index(
    trace_path: Path,
) -> tuple[list[TraceIndexEntry], dict[str, int]]:
    """加载或重建索引。

    Returns:
        (ordered_entries, offset_by_trace_id)
    """
    entries = _try_load_idx(trace_path)
    if entries is not None:
        return entries, _to_offset_map(entries)

    # 索引不存在或已损坏／过时 → 重建
    entries = _build_index_from_jsonl(trace_path)
    return entries, _to_offset_map(entries)


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

    # 检查索引是否与 JSONL 行数对齐
    jsonl_lines = _count_nonempty_lines(trace_path)
    if len(entries) != jsonl_lines:
        logger.info(
            "trace 索引行数不匹配，重建：path=%s idx=%d jsonl=%d",
            trace_path,
            len(entries),
            jsonl_lines,
        )
        return None

    return entries


def _build_index_from_jsonl(trace_path: Path) -> list[TraceIndexEntry]:
    """全量扫描 JSONL 重建索引并持久化。"""
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

    # 持久化重建的索引
    try:
        with open(idx_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("写入 trace 索引失败：%s err=%s", idx_path, exc)

    return entries


def _to_offset_map(
    entries: list[TraceIndexEntry],
) -> dict[str, int]:
    """转换为 ``{trace_id: offset}`` 映射。"""
    return {e["trace_id"]: e["offset"] for e in entries}


def _count_nonempty_lines(path: Path) -> int:
    """快速统计 JSONL 非空行数。"""
    count = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
    except OSError:
        pass
    return count
