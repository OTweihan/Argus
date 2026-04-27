"""LLM 重试逻辑。"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from argus_py.core.constants import DEFAULT_LLM_MAX_RETRIES
from argus_py.core.exceptions import LLMError, LLMRateLimitError

T = TypeVar("T")


@dataclass(frozen=True)
class RetryConfig:
    """异步重试配置。"""

    max_retries: int = DEFAULT_LLM_MAX_RETRIES
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 8.0

    def delay_for_attempt(self, attempt: int) -> float:
        """根据重试次数计算退避时间。"""
        return min(self.base_delay_seconds * (2 ** attempt), self.max_delay_seconds)


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    retry_config: RetryConfig | None = None,
    retryable_errors: tuple[type[Exception], ...] = (LLMRateLimitError,),
) -> T:
    """执行异步操作并按配置重试。"""
    config = retry_config or RetryConfig()
    last_exc: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            return await operation()
        except retryable_errors as exc:
            last_exc = exc
            if attempt >= config.max_retries:
                break
            await asyncio.sleep(config.delay_for_attempt(attempt))

    raise LLMError(f"LLM 调用重试 {config.max_retries + 1} 次后仍失败：{last_exc}")


def with_retry(
    max_retries: int = DEFAULT_LLM_MAX_RETRIES,
    retryable_errors: tuple[type[Exception], ...] = (LLMRateLimitError,),
    base_delay: float = 1.0,
):
    """异步函数重试装饰器。"""

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs) -> T:
            config = RetryConfig(max_retries=max_retries, base_delay_seconds=base_delay)
            return await retry_async(
                lambda: fn(*args, **kwargs),
                retry_config=config,
                retryable_errors=retryable_errors,
            )

        return wrapper

    return decorator
