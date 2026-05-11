"""日志上下文管理。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any
from uuid import uuid4

_request_id: ContextVar[str | None] = ContextVar("argus_request_id", default=None)
_task_id: ContextVar[str | None] = ContextVar("argus_task_id", default=None)
_operation: ContextVar[str | None] = ContextVar("argus_operation", default=None)
_actor: ContextVar[str | None] = ContextVar("argus_actor", default=None)


def new_request_id() -> str:
    """生成请求链路 ID。"""
    return f"req_{uuid4().hex}"


def current_context() -> dict[str, str | None]:
    """返回当前日志上下文。"""
    return {
        "request_id": _request_id.get(),
        "task_id": _task_id.get(),
        "operation": _operation.get(),
        "actor": _actor.get(),
    }


@contextmanager
def bind_context(
    *,
    request_id: str | None = None,
    task_id: str | None = None,
    operation: str | None = None,
    actor: str | None = None,
) -> Iterator[None]:
    """在当前执行上下文中绑定日志字段。"""
    tokens: list[tuple[ContextVar[Any], Token[Any]]] = []
    if request_id is not None:
        tokens.append((_request_id, _request_id.set(request_id)))
    if task_id is not None:
        tokens.append((_task_id, _task_id.set(task_id)))
    if operation is not None:
        tokens.append((_operation, _operation.set(operation)))
    if actor is not None:
        tokens.append((_actor, _actor.set(actor)))
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)
