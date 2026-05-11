"""服务方法操作切面。"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from time import perf_counter
from typing import Any, TypeVar, cast

from argus_py.observability.context import bind_context
from argus_py.observability.redaction import redact

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
                _log_finish(logger, event, "error", started, include_args, signature, args, kwargs)
            raise
        if _operation_logging_enabled():
            _log_finish(logger, event, "success", started, include_args, signature, args, kwargs)
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
                _log_finish(logger, event, "error", started, include_args, signature, args, kwargs)
            raise
        if _operation_logging_enabled():
            _log_finish(logger, event, "success", started, include_args, signature, args, kwargs)
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
    details: dict[str, Any] = {}
    if include_args:
        details["args"] = _bound_arguments(signature, args, kwargs)
    logger.info(
        "%s %s",
        event,
        "完成" if status == "success" else "失败",
        extra={
            "event": event,
            "status": status,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "details": details or None,
        },
        exc_info=status == "error",
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
    return redact({key: value for key, value in bound.arguments.items() if key != "self"})


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


@functools.lru_cache(maxsize=1)
def _operation_logging_enabled() -> bool:
    from argus_py.config.server_settings import load_server_settings  # noqa: PLC0415

    return load_server_settings().observability_operation_logging
