"""服务方法操作切面。"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from time import perf_counter
from typing import Any, TypeVar, cast

from argus_py.observability.context import bind_context
from argus_py.observability.events import STATUS_ERROR, STATUS_SUCCESS, log_event
from argus_py.observability.redaction import redact
from argus_py.utils.jsonx import to_jsonable

F = TypeVar("F", bound=Callable[..., Any])


def log_operation(
    event: str,
    *,
    logger_name: str = "argus.operation",
    include_args: bool = False,
    task_arg: str | None = None,
) -> Callable[[F], F]:
    """记录函数或协程的执行结果、耗时和上下文。"""

    def decorator(func: F) -> F:
        operation = f"{func.__module__}.{func.__qualname__}"
        logger = logging.getLogger(logger_name)
        signature = inspect.signature(func)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await _run_async(
                    func,
                    args,
                    kwargs,
                    event=event,
                    operation=operation,
                    logger=logger,
                    signature=signature,
                    include_args=include_args,
                    task_arg=task_arg,
                )

            return cast(F, async_wrapper)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return _run_sync(
                func,
                args,
                kwargs,
                event=event,
                operation=operation,
                logger=logger,
                signature=signature,
                include_args=include_args,
                task_arg=task_arg,
            )

        return cast(F, wrapper)

    return decorator


async def _run_async(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    event: str,
    operation: str,
    logger: logging.Logger,
    signature: inspect.Signature,
    include_args: bool,
    task_arg: str | None,
) -> Any:
    task_id = _task_id_from_call(signature, args, kwargs, task_arg)
    started = perf_counter()
    with bind_context(task_id=task_id, operation=operation):
        try:
            result = await func(*args, **kwargs)
        except Exception:
            if _operation_logging_enabled():
                _log_finish(
                    logger, event, STATUS_ERROR, started, include_args, signature, args, kwargs
                )
            raise
        if _operation_logging_enabled():
            _log_finish(
                logger, event, STATUS_SUCCESS, started, include_args, signature, args, kwargs
            )
        return result


def _run_sync(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    event: str,
    operation: str,
    logger: logging.Logger,
    signature: inspect.Signature,
    include_args: bool,
    task_arg: str | None,
) -> Any:
    task_id = _task_id_from_call(signature, args, kwargs, task_arg)
    started = perf_counter()
    with bind_context(task_id=task_id, operation=operation):
        try:
            result = func(*args, **kwargs)
        except Exception:
            if _operation_logging_enabled():
                _log_finish(
                    logger, event, STATUS_ERROR, started, include_args, signature, args, kwargs
                )
            raise
        if _operation_logging_enabled():
            _log_finish(
                logger, event, STATUS_SUCCESS, started, include_args, signature, args, kwargs
            )
        return result


def _log_finish(
    logger: logging.Logger,
    event: str,
    status: str,
    started: float,
    include_args: bool,
    signature: inspect.Signature,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    details: dict[str, Any] | None = None
    if include_args:
        bound = _bound_arguments(signature, args, kwargs)
        if bound:
            details = {"args": bound}
    log_event(
        logger,
        event,
        status=status,
        duration_ms=round((perf_counter() - started) * 1000, 2),
        details=details,
        exc_info=status == STATUS_ERROR,
    )


def _bound_arguments(
    signature: inspect.Signature,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    try:
        bound = signature.bind_partial(*args, **kwargs)
    except TypeError:
        return {}
    raw = {key: value for key, value in bound.arguments.items() if key != "self"}
    # 先 to_jsonable 把 dataclass/Pydantic/datetime/Path 等转成可序列化结构，
    # 再脱敏，避免日志里只看到对象 repr 而丢失结构。
    return redact(to_jsonable(raw))


def _task_id_from_call(
    signature: inspect.Signature,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    task_arg: str | None,
) -> str | None:
    if task_arg is None:
        return None
    try:
        bound = signature.bind_partial(*args, **kwargs)
    except TypeError:
        return None
    value = bound.arguments.get(task_arg)
    if isinstance(value, str):
        return value
    return getattr(value, "task_id", None)


_OPERATION_LOGGING_CACHE: bool | None = None


def _operation_logging_enabled() -> bool:
    """读取并缓存 operation_logging 配置；测试可通过 reset 清空缓存。"""
    global _OPERATION_LOGGING_CACHE
    if _OPERATION_LOGGING_CACHE is None:
        from argus_py.config.server_settings import load_server_settings  # noqa: PLC0415

        _OPERATION_LOGGING_CACHE = load_server_settings().observability_operation_logging
    return _OPERATION_LOGGING_CACHE


def reset_operation_logging_cache() -> None:
    """清空 ``_operation_logging_enabled`` 的缓存；仅供测试或配置热重载使用。"""
    global _OPERATION_LOGGING_CACHE
    _OPERATION_LOGGING_CACHE = None
