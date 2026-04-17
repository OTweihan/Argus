"""LLM retry logic with exponential backoff."""

import asyncio
import functools
from typing import Callable, Type

from argus_py.core.constants import DEFAULT_LLM_MAX_RETRIES
from argus_py.core.exceptions import LLMError, LLMRateLimitError


def with_retry(
    max_retries: int = DEFAULT_LLM_MAX_RETRIES,
    retryable_errors: tuple = (LLMRateLimitError,),
    base_delay: float = 1.0,
):
    """Decorator that retries async functions with exponential backoff.

    Args:
        max_retries: Maximum retry attempts.
        retryable_errors: Exception types that trigger retry.
        base_delay: Initial delay in seconds (doubles each retry).
    """
    def decorator(fn: Callable):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except retryable_errors as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        print(f"[LLM] Retry {attempt + 1}/{max_retries} after {delay}s: {exc}")
                        await asyncio.sleep(delay)
                        delay *= 2
            raise LLMError(f"Failed after {max_retries + 1} attempts: {last_exc}")
        return wrapper
    return decorator
