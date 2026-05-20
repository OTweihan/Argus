"""日志上下文管理。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any
from uuid import uuid4

_request_id: ContextVar[str | None] = ContextVar("argus_request_id", default=None)
_task_id: ContextVar[str | None] = ContextVar("argus_task_id", default=None)
_operation: ContextVar[str | None] = ContextVar("argus_operation", default=None)
_actor: ContextVar[str | None] = ContextVar("argus_actor", default=None)

# 进程级 IO 线程池（由容器/ lifespan 设置）。None = 使用 event loop 默认 executor。
_io_executor: ThreadPoolExecutor | None = None


def set_io_executor(executor: ThreadPoolExecutor) -> None:
    """设置全局 IO 线程池。"""
    global _io_executor
    _io_executor = executor


def io_executor_stats() -> dict[str, int]:
    """返回 IO 线程池排队深度。"""
    if _io_executor is None:
        return {"queued": -1}
    return {"queued": _io_executor._work_queue.qsize()}


def new_request_id() -> str:
    """生成请求链路 ID。"""
    return f"req_{uuid4().hex}"


async def run_in_thread(func: Callable[..., object], *args: Any, **kwargs: Any) -> Any:
    """在线程池中执行 func，传播 request 上下文（request_id / task_id 等）。

    使用专用 IO 线程池（``io_executor`` 非空时），否则回退到 event loop 默认 executor。
    线程切换前捕获当前上下文，在目标线程通过 ``bind_context`` 恢复。
    """
    ctx = current_context()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _io_executor, lambda: _run_with_context(ctx, func, *args, **kwargs)
    )


def _run_with_context(
    ctx: dict[str, str | None], func: Callable[..., object], *args: Any, **kwargs: Any
) -> object:
    with bind_context(**ctx):
        return func(*args, **kwargs)


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
