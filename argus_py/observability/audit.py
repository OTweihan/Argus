"""业务审计日志服务。"""

from __future__ import annotations

import logging
from typing import Any, Callable

from argus_py.observability.redaction import redact
from argus_py.utils.jsonx import to_jsonable

AuditEventPublisher = Callable[[str, str, dict[str, Any]], None]


class AuditService:
    """记录用户可感知的业务动作，并可同步发布到事件总线。"""

    def __init__(self, event_publisher: AuditEventPublisher | None = None) -> None:
        self.event_publisher = event_publisher
        self.logger = logging.getLogger("argus.audit")

    def record(
        self,
        action: str,
        *,
        task_id: str | None = None,
        status: str = "success",
        details: dict[str, Any] | None = None,
    ) -> None:
        """记录一条审计事件。"""
        payload = redact(to_jsonable(details or {}))
        self.logger.info(
            "审计事件：%s",
            action,
            extra={"event": action, "status": status, "details": payload},
        )
        if self.event_publisher is None or task_id is None:
            return
        self.event_publisher(
            "audit.log",
            task_id,
            {"action": action, "status": status, "details": payload},
        )
