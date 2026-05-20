"""LLM 调用追踪读取服务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from argus_py.core.exceptions import TaskError
from argus_py.core.paths import OUTPUT_DIR


def _resolve_trace_path(task_id: str) -> Path:
    """解析并校验 trace 文件路径，防止目录穿越。"""
    raw = (OUTPUT_DIR / "traces" / f"{task_id}.jsonl").resolve()
    if not raw.is_relative_to(OUTPUT_DIR.resolve()):
        raise TaskError("trace 路径不在允许的输出目录下。")
    return raw


class TraceReadService:
    """LLM 调用追踪记录的只读查询。

    不需要 storage 依赖，仅通过 trace 文件路径索引随机访问。
    """

    def list_llm_traces(
        self,
        task_id: str,
        skip: int = 0,
        limit: int = 50,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回任务的 LLM 调用追踪记录（通过行号偏移索引随机访问）。"""
        trace_path = _resolve_trace_path(task_id)
        if not trace_path.exists():
            return []

        from argus_py.observability.trace_index import load_trace_index

        entries, offset_map = load_trace_index(trace_path)
        if not entries:
            return []

        if trace_id:
            offset = offset_map.get(trace_id)
            if offset is None or skip > 0:
                return []
            with open(trace_path, encoding="utf-8") as f:
                f.seek(offset)
                return [json.loads(f.readline())]

        skip = max(skip, 0)
        stop: int | None = (skip + limit) if limit > 0 else None
        window = entries[skip:stop]
        results: list[dict[str, Any]] = []
        with open(trace_path, encoding="utf-8") as f:
            for entry in window:
                f.seek(entry["offset"])
                results.append(json.loads(f.readline()))
        return results

    def get_llm_trace_detail(
        self,
        task_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        """返回单条 LLM 调用的完整追踪记录（通过偏移索引 O(1) 定位）。"""
        trace_path = _resolve_trace_path(task_id)
        if not trace_path.exists():
            return None

        from argus_py.observability.trace_index import load_trace_index

        _, offset_map = load_trace_index(trace_path)
        offset = offset_map.get(trace_id)
        if offset is None:
            return None

        with open(trace_path, encoding="utf-8") as f:
            f.seek(offset)
            return json.loads(f.readline())
