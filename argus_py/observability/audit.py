"""业务审计日志服务。"""

from __future__ import annotations

import logging
import threading
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


# ── 模块级注册表：让 audit() 零侵入接入 AuditService ──

_AUDIT_SERVICE: AuditService | None = None
"""运行时注册的 AuditService 实例。仅在容器上下文（API 服务器）中存在。"""

_AUDIT_LOCK = threading.Lock()
"""保护 _AUDIT_SERVICE 的线程锁，防止并发 set 与读取形成 data race。"""


def set_audit_service(service: AuditService) -> None:
    """注册 AuditService 实例，使 audit() 函数能够发布事件总线。

    在容器初始化时调用一次，CLI/脚本中无需调用。

    线程安全：多线程同时调用时仅第一次生效，后续调用会记录 warning。
    服务重启（hot reload）会重新加载模块，重新注册。
    """
    global _AUDIT_SERVICE
    with _AUDIT_LOCK:
        if _AUDIT_SERVICE is not None:
            logging.getLogger("argus.audit").warning(
                "audit service 已注册，忽略重复调用：%r",
                service,
            )
            return
        _AUDIT_SERVICE = service


def audit(
    action: str,
    *,
    task_id: str | None = None,
    status: str = "success",
    **details: Any,
) -> None:
    """记录一条业务审计事件。

    容器上下文（API 服务器）中，通过 ``AuditService`` 同时写入日志和事件总线；
    CLI/脚本中等零依赖上下文只写入 ``argus.audit`` logger。

    与 ``@log_operation`` 的运维侧 trace 互补。``**details`` 中的字段会经过
    敏感字段脱敏。
    """
    if _AUDIT_SERVICE is not None:
        _AUDIT_SERVICE.record(action, task_id=task_id, status=status, details=details or None)
        return

    # 零依赖降级路径：仅写日志，不发事件总线
    payload = redact(to_jsonable(details)) if details else {}
    extra: dict[str, Any] = {"event": action, "status": status}
    if payload:
        extra["details"] = payload
    if task_id is not None:
        extra["task_id"] = task_id
    logging.getLogger("argus.audit").info("审计事件：%s", action, extra=extra)


__all__ = ["AuditEventPublisher", "AuditService", "audit"]
