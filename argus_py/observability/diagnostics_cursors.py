"""诊断事件 ID / 分页游标编解码与跨文件排序键。

亦包含 search 用的有界 top-heap 辅助（``_push_top_event`` /
``_finalize_top_events``）：它们依赖 ``event_sort_key`` 的稳定次序约定，
与游标锚点比较同属「跨文件排序」支撑，故与编解码放在同一模块。
"""

from __future__ import annotations

import base64
import heapq
import json
from dataclasses import dataclass

from argus_py.observability.diagnostics_models import (
    DiagnosticsBadRequestError,
    DiagnosticsEvent,
    DiagnosticsNotFoundError,
)


def _b64_encode(payload: str) -> str:
    """URL 安全 base64（去填充，便于直接作为路径参数）。"""
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def _encode_event_id(rel_path: str, line_no: int) -> str:
    """编码旧版行号事件 ID（保留给已有链接与兼容性测试）。"""
    return _b64_encode(json.dumps({"f": rel_path, "l": line_no}, ensure_ascii=False))


@dataclass(frozen=True)
class EventLocator:
    file: str
    line: int | None = None
    offset: int | None = None
    timestamp: str | None = None


# 兼容旧私有名（store / 历史单测）。
_EventLocator = EventLocator


def _encode_event_locator(locator: EventLocator) -> str:
    payload: dict[str, object] = {"f": locator.file}
    if locator.offset is not None:
        payload["o"] = locator.offset
    elif locator.line is not None:
        payload["l"] = locator.line
    else:  # pragma: no cover - 内部构造器保证至少有一种位置
        raise ValueError("事件定位器缺少行号或字节偏移")
    if locator.timestamp is not None:
        payload["t"] = locator.timestamp
    return _b64_encode(json.dumps(payload, ensure_ascii=False))


def _decode_event_id(event_id: str) -> _EventLocator:
    try:
        payload = json.loads(_b64_decode(event_id))
        rel_path = str(payload["f"])
        line_no = int(payload["l"]) if "l" in payload else None
        offset = int(payload["o"]) if "o" in payload else None
        timestamp = str(payload["t"]) if payload.get("t") is not None else None
    except Exception as exc:  # noqa: BLE001 — 任何畸形输入都视为不存在
        raise DiagnosticsNotFoundError(f"事件不存在或已轮转：{event_id!r}") from exc
    invalid_position = (line_no is None) == (offset is None)
    if (
        invalid_position
        or (line_no is not None and line_no < 1)
        or (offset is not None and offset < 0)
        or not rel_path
        or "\x00" in rel_path
    ):
        raise DiagnosticsNotFoundError(f"事件不存在或已轮转：{event_id!r}")
    return _EventLocator(
        file=rel_path,
        line=line_no,
        offset=offset,
        timestamp=timestamp,
    )


@dataclass(frozen=True)
class _CursorPos:
    locator: EventLocator
    timestamp: str


def event_sort_key(
    event: DiagnosticsEvent,
    *,
    file: str | None = None,
    offset: int | None = None,
) -> tuple[str, str, int]:
    """跨文件归并排序键；取 max 即为最新。

    稳定次序（对外约定，max）：timestamp DESC → file 路径 DESC → offset DESC。
    热路径可传入已有 ``file``/``offset``，避免反复解码 event_id。
    """
    if file is None or offset is None:
        locator = _decode_event_id(event.event_id)
        file = locator.file if file is None else file
        if offset is None:
            offset = locator.offset if locator.offset is not None else -(locator.line or 0)
    return (event.timestamp or "", file, offset)


def _is_strictly_older_than_cursor(
    event: DiagnosticsEvent,
    cursor: _CursorPos,
    *,
    sort_key: tuple[str, str, int] | None = None,
) -> bool:
    """事件是否严格排在游标锚点「更旧」一侧（不含锚点本身）。

    即 sort_key(event) < sort_key(cursor_anchor)，与归并 max 次序一致。
    """
    event_key = sort_key if sort_key is not None else event_sort_key(event)
    cursor_offset = (
        cursor.locator.offset if cursor.locator.offset is not None else -(cursor.locator.line or 0)
    )
    cursor_key = (cursor.timestamp or "", cursor.locator.file, cursor_offset)
    return event_key < cursor_key


def _push_top_event(
    heap: list[tuple[tuple[str, str, int], int, DiagnosticsEvent]],
    *,
    key: tuple[str, str, int],
    seq: int,
    event: DiagnosticsEvent,
    limit: int,
) -> bool:
    """将匹配事件推入大小为 limit 的最小堆；返回是否已超出 limit（有更多）。

    堆元素为 (sort_key, seq, event)：seq 打破同键比较，避免 event 不可比路径。
    """
    if limit <= 0:
        return True
    item = (key, seq, event)
    if len(heap) < limit:
        heapq.heappush(heap, item)
        return False
    if key > heap[0][0]:
        heapq.heapreplace(heap, item)
    return True


def _finalize_top_events(
    heap: list[tuple[tuple[str, str, int], int, DiagnosticsEvent]],
) -> list[tuple[tuple[str, str, int], DiagnosticsEvent]]:
    """最小堆 → sort_key 降序列表，供 k-way 线性推进。"""
    return sorted(
        ((key, event) for key, _seq, event in heap), key=lambda item: item[0], reverse=True
    )


def _encode_cursor(event: DiagnosticsEvent) -> str:
    locator = _decode_event_id(event.event_id)
    payload: dict[str, object] = {"f": locator.file, "t": event.timestamp}
    if locator.offset is not None:
        payload["o"] = locator.offset
    else:
        payload["l"] = locator.line
    return _b64_encode(json.dumps(payload, ensure_ascii=False))


def _decode_cursor(cursor: str | None) -> _CursorPos | None:
    if not cursor:
        return None
    try:
        payload = json.loads(_b64_decode(cursor))
        line_no = int(payload["l"]) if "l" in payload else None
        offset = int(payload["o"]) if "o" in payload else None
        pos = _CursorPos(
            locator=_EventLocator(
                file=str(payload["f"]),
                line=line_no,
                offset=offset,
                timestamp=str(payload["t"]),
            ),
            timestamp=str(payload["t"]),
        )
    except Exception as exc:  # noqa: BLE001
        raise DiagnosticsBadRequestError("非法分页游标") from exc
    locator = pos.locator
    invalid_position = (locator.line is None) == (locator.offset is None)
    if (
        invalid_position
        or (locator.line is not None and locator.line < 1)
        or (locator.offset is not None and locator.offset < 0)
        or not locator.file
        or "\x00" in locator.file
    ):
        raise DiagnosticsBadRequestError("非法分页游标")
    return pos
