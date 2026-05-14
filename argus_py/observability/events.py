"""语义化日志事件 helper。

封装"事件式"日志的常用 extra 字段（event/status/duration_ms/details/http），
让调用方写：

    log_event(logger, "task.create", status="success", details={...})

而无需每次重复手写 ``extra=dict(event=..., status=..., ...)``。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    status: str = STATUS_SUCCESS,
    duration_ms: float | None = None,
    details: Mapping[str, Any] | None = None,
    http: Mapping[str, Any] | None = None,
    message: str | None = None,
    level: int | None = None,
    exc_info: bool = False,
) -> None:
    """记录一条业务事件日志。

    Args:
        logger: 调用方持有的 logger 实例。
        event: 事件名（建议 ``namespace.action`` 形式，如 ``task.create``）。
        status: ``success`` / ``error`` / ``cancelled`` / 自定义。
        duration_ms: 操作耗时（毫秒），可选。
        details: 额外结构化字段；会经过 ``JsonLogFormatter`` 的脱敏处理。
        http: HTTP 相关字段（与请求日志保持一致的子对象），可选。
        message: 自定义可读消息，缺省时按 ``"{event} {状态}"`` 生成。
        level: 显式日志级别。默认 ``error``/``cancelled`` 用 WARNING（异常配
            合 ``exc_info=True`` 会触发 traceback 输出），其余用 INFO。
        exc_info: 是否附带异常 traceback；通常仅在异常分支启用。
    """
    extra: dict[str, Any] = {"event": event, "status": status}
    if duration_ms is not None:
        extra["duration_ms"] = duration_ms
    if details:
        extra["details"] = dict(details)
    if http:
        extra["http"] = dict(http)

    if level is None:
        level = logging.WARNING if status in {STATUS_ERROR, STATUS_CANCELLED} else logging.INFO

    if message is None:
        message = f"{event} {_status_text(status)}"

    logger.log(level, message, extra=extra, exc_info=exc_info)


def _status_text(status: str) -> str:
    return {
        STATUS_SUCCESS: "完成",
        STATUS_ERROR: "失败",
        STATUS_CANCELLED: "取消",
    }.get(status, status)


__all__ = ["STATUS_CANCELLED", "STATUS_ERROR", "STATUS_SUCCESS", "log_event"]
