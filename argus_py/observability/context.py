"""日志上下文管理。"""

from __future__ import annotations

import asyncio
import os
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
# 仅用于 run_in_thread 快照透传 / 测试覆盖；正常路径读进程级 runId。
_run_id_override: ContextVar[str | None] = ContextVar("argus_run_id_override", default=None)

# 进程级启动会话 ID：进程生命周期内稳定，写入结构化日志的 runId 字段，
# 便于诊断中心按一次启动会话聚合 Python / Java / Web 日志。
# 可由 ARGUS_RUN_ID 注入（与 Java/Compose 对齐）；缺省自生成。
_process_run_id: str | None = None

# 进程级 IO 线程池（由容器/ lifespan 设置）。None = 使用 event loop 默认 executor。
_io_executor: ThreadPoolExecutor | None = None


def set_io_executor(executor: ThreadPoolExecutor | None) -> None:
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


def new_run_id() -> str:
    """生成进程级启动会话 ID。"""
    return f"run_{uuid4().hex}"


def init_process_run_id(run_id: str | None = None) -> str:
    """初始化或覆盖进程级 runId，返回最终值。

    优先使用显式参数，其次 ``ARGUS_RUN_ID`` 环境变量，最后自生成。
    lifespan / CLI 启动时调用一次即可；重复调用会覆盖（测试可重置）。
    """
    global _process_run_id
    explicit = (run_id or "").strip()
    env_value = (os.getenv("ARGUS_RUN_ID") or "").strip()
    _process_run_id = explicit or env_value or new_run_id()
    return _process_run_id


def get_process_run_id() -> str:
    """返回当前生效的 runId（ContextVar 覆盖优先，否则进程级）。"""
    override = _run_id_override.get()
    if override is not None:
        return override
    global _process_run_id
    if _process_run_id is None:
        return init_process_run_id()
    return _process_run_id


def reset_process_run_id() -> None:
    """清空进程 runId（仅测试使用）。"""
    global _process_run_id
    _process_run_id = None


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
    """返回当前日志上下文（含进程级 run_id）。"""
    return {
        "request_id": _request_id.get(),
        "task_id": _task_id.get(),
        "operation": _operation.get(),
        "actor": _actor.get(),
        "run_id": get_process_run_id(),
    }


@contextmanager
def bind_context(
    *,
    request_id: str | None = None,
    task_id: str | None = None,
    operation: str | None = None,
    actor: str | None = None,
    run_id: str | None = None,
) -> Iterator[None]:
    """在当前执行上下文中绑定日志字段。

    ``run_id`` 通常来自 ``current_context()`` 快照透传；进程级值由
    ``init_process_run_id`` 管理，此处仅通过 ContextVar 做作用域覆盖。
    """
    tokens: list[tuple[ContextVar[Any], Token[Any]]] = []
    if request_id is not None:
        tokens.append((_request_id, _request_id.set(request_id)))
    if task_id is not None:
        tokens.append((_task_id, _task_id.set(task_id)))
    if operation is not None:
        tokens.append((_operation, _operation.set(operation)))
    if actor is not None:
        tokens.append((_actor, _actor.set(actor)))
    if run_id is not None:
        tokens.append((_run_id_override, _run_id_override.set(run_id)))
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)
