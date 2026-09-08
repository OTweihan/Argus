"""诊断日志领域模型与异常（可被 store / export 共用）。

本模块无 IO；游标编解码见 ``diagnostics_cursors``，读盘见 ``diagnostics_io``。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# 日志级别排序（公开给导出等旁路模块复用；值越大越严重）。
LEVEL_ORDER: dict[str, int] = {
    "TRACE": 0,
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
    "FATAL": 50,
}


@dataclass(frozen=True)
class DiagnosticsQuery:
    """日志检索条件（字段命名沿用方案 8.2，Python 侧 snake_case）。"""

    time_from: datetime | None = None
    time_to: datetime | None = None
    component: str | None = None
    level: str | None = None
    keyword: str | None = None
    request_id: str | None = None
    run_id: str | None = None
    limit: int = 100
    cursor: str | None = None


@dataclass(frozen=True)
class DiagnosticsEvent:
    """统一诊断日志事件（wire 字段 camelCase，见方案 14.2）。"""

    event_id: str
    timestamp: str
    level: str
    component: str
    module: str
    message: str
    request_id: str | None = None
    run_id: str | None = None
    exception: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        """转为 camelCase wire 字典（不含 raw，raw 仅详情返回）。"""
        return {
            "eventId": self.event_id,
            "timestamp": self.timestamp,
            "level": self.level,
            "component": self.component,
            "module": self.module,
            "message": self.message,
            "requestId": self.request_id,
            "runId": self.run_id,
            "exception": self.exception,
        }


@dataclass(frozen=True)
class DiagnosticsPage:
    """游标分页结果（方案 8.6）。"""

    items: list[DiagnosticsEvent]
    next_cursor: str | None
    has_more: bool
    scan_limited: bool = False

    def to_wire(self) -> dict[str, Any]:
        return {
            "items": [event.to_wire() for event in self.items],
            "nextCursor": self.next_cursor,
            "hasMore": self.has_more,
            "scanLimited": self.scan_limited,
        }


@dataclass
class DiagnosticsScanBudget:
    """跨多次 ``search`` 共享的扫描字节预算（导出 / 诊断包，D-01）。

    普通单页查询不传此对象，仍使用 store 的单次 ``_scan_max_bytes``。
    协作取消：``cancel_event`` 或 ``deadline_monotonic`` 触发后停止继续读盘，
    并标记 ``limited``（映射为 ``scanLimited``）。
    """

    max_bytes: int
    cancel_event: threading.Event | None = None
    deadline_monotonic: float | None = None
    limited: bool = False
    _remaining: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._remaining = max(0, int(self.max_bytes))

    @property
    def remaining(self) -> int:
        return max(0, self._remaining)

    @property
    def consumed(self) -> int:
        return max(0, int(self.max_bytes) - self._remaining)

    def cancelled(self) -> bool:
        if self.cancel_event is not None and self.cancel_event.is_set():
            return True
        if self.deadline_monotonic is not None and time.monotonic() >= self.deadline_monotonic:
            return True
        return False

    def consume(self, nbytes: int) -> None:
        self._remaining = max(0, self._remaining - max(0, int(nbytes)))

    def mark_limited(self) -> None:
        self.limited = True


@dataclass(frozen=True)
class RunFileInfo:
    name: str
    size_bytes: int
    modified_at: str


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    started_at: str
    files: list[RunFileInfo]
    total_bytes: int

    def to_wire(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "startedAt": self.started_at,
            "files": [
                {"name": f.name, "sizeBytes": f.size_bytes, "modifiedAt": f.modified_at}
                for f in self.files
            ],
            "totalBytes": self.total_bytes,
        }


class DiagnosticsNotFoundError(LookupError):
    """事件或启动会话不存在（路由层转 404）。"""


class DiagnosticsBadRequestError(ValueError):
    """非法游标 / 非法标识（路由层转 400）。"""
