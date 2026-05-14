"""结构化日志 formatter 和上下文字段注入。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from argus_py.observability.context import current_context
from argus_py.observability.redaction import redact

# LogRecord 自带的内置属性集合，用于从 extra 中过滤掉
_BUILTIN_RECORD_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",  # Python 3.12+
        "thread",
        "threadName",
    }
)

# 白名单字段 → JSON 输出 key 的映射；命中的字段直接放到 payload 顶层
_WHITELIST_ATTR_MAP: dict[str, str] = {
    "request_id": "requestId",
    "task_id": "taskId",
    "operation": "operation",
    "actor": "actor",
    "event": "event",
    "status": "status",
    "duration_ms": "durationMs",
    "details": "details",
    "http": "http",
}

# 异常 traceback 截断阈值（字节，按字符长度近似）
_MAX_EXCEPTION_LENGTH = 8 * 1024
_TRUNCATED_SUFFIX = "\n...truncated..."


class ContextLogFilter(logging.Filter):
    """把 contextvars 中的链路字段注入 LogRecord。"""

    def filter(self, record: logging.LogRecord) -> bool:
        context = current_context()
        for key, value in context.items():
            setattr(record, key, value)
        return True


class JsonLogFormatter(logging.Formatter):
    """输出单行 JSON 日志。

    输出字段：
    - 顶层固定：timestamp / level / logger / message / module / function / line
    - 顶层白名单（命中才输出）：requestId / taskId / operation / actor /
      event / status / durationMs / details / http
    - extra 子对象：调用方 ``logger.info(..., extra={"foo": "bar"})`` 中
      未被白名单收纳的字段都会归集到 ``extra`` 下，并经过递归脱敏。
    - exception / stack：超过阈值会被截断，避免日志条目过大。
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        for attr, output in _WHITELIST_ATTR_MAP.items():
            value = getattr(record, attr, None)
            if value is not None:
                payload[output] = redact(value)

        extra = self._collect_extra(record)
        if extra:
            payload["extra"] = redact(extra)

        if record.exc_info:
            payload["exception"] = _truncate(self.formatException(record.exc_info))
        if record.stack_info:
            payload["stack"] = _truncate(self.formatStack(record.stack_info))

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)

    @staticmethod
    def _collect_extra(record: logging.LogRecord) -> dict[str, Any]:
        """收集 record 中既不在白名单、也不是内置属性的字段。"""
        extra: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _BUILTIN_RECORD_ATTRS or key in _WHITELIST_ATTR_MAP:
                continue
            if key.startswith("_"):
                continue
            extra[key] = value
        return extra


def _truncate(text: str, max_length: int = _MAX_EXCEPTION_LENGTH) -> str:
    """按字符长度截断超长文本（traceback / stack）。"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + _TRUNCATED_SUFFIX


def get_observable_logger(name: str) -> logging.Logger:
    """获取带语义命名的 logger。"""
    return logging.getLogger(name)
