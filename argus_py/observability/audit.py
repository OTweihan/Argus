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


_AUDIT_LOGGER = logging.getLogger("argus.audit")


def audit(
    action: str,
    *,
    task_id: str | None = None,
    status: str = "success",
    **details: Any,
) -> None:
    """记录一条审计事件到 ``argus.audit`` logger（不发布事件总线）。

    用于"用户可感知的业务动作"埋点（任务/项目/模型配置 CRUD、登录态变更等），
    与 ``@log_operation`` 的运维侧 trace 互补。``**details`` 中的字段会作为
    审计 payload 的 ``details`` 子对象写入日志，并经过敏感字段脱敏。

    本函数零运行时依赖，可在 CLI / 一次性脚本中安全调用——不会触发
    RuntimeContainer 初始化。若需同时发布事件总线，请直接调用
    ``AuditService.record``。

    例：

        audit("task.create", task_id=task.task_id, goal=task.goal)
    """
    payload = redact(to_jsonable(details)) if details else {}
    extra: dict[str, Any] = {"event": action, "status": status}
    if payload:
        extra["details"] = payload
    if task_id is not None:
        extra["task_id"] = task_id
    _AUDIT_LOGGER.info("审计事件：%s", action, extra=extra)


__all__ = ["AuditEventPublisher", "AuditService", "audit"]
