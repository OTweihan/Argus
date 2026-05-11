"""结构化日志 formatter 和上下文字段注入。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from argus_py.observability.context import current_context
from argus_py.observability.redaction import redact


class ContextLogFilter(logging.Filter):
    """把 contextvars 中的链路字段注入 LogRecord。"""

    def filter(self, record: logging.LogRecord) -> bool:
        context = current_context()
        for key, value in context.items():
            setattr(record, key, value)
        return True


class JsonLogFormatter(logging.Formatter):
    """输出单行 JSON 日志。"""

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
        for attr, output in {
            "request_id": "requestId",
            "task_id": "taskId",
            "operation": "operation",
            "actor": "actor",
            "event": "event",
            "status": "status",
            "duration_ms": "durationMs",
            "details": "details",
            "http": "http",
        }.items():
            value = getattr(record, attr, None)
            if value is not None:
                payload[output] = redact(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def get_observable_logger(name: str) -> logging.Logger:
    """获取带语义命名的 logger。"""
    return logging.getLogger(name)
