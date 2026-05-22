"""验证 run_in_thread 的 ContextVar 传播与取消行为。

新增 issue-9：asyncio.to_thread 不复制 ContextVar，导致线程内日志
取不到 request_id。run_in_thread 在切换线程前捕获上下文，在入口恢复。
"""

from __future__ import annotations

import asyncio

import pytest
from argus_py.observability.context import (
    _request_id,
    _task_id,
    bind_context,
    current_context,
    run_in_thread,
)


def _read_request_id() -> str | None:
    """在线程池线程中读取 request_id ContextVar。"""
    return _request_id.get()


def _read_task_id() -> str | None:
    return _task_id.get()


def _return_arg(arg: str) -> str:
    return arg


class TestContextPropagation:
    """ContextVar 通过 run_in_thread 传播到线程池线程。"""

    @pytest.mark.asyncio
    async def test_propagates_request_id(self) -> None:
        with bind_context(request_id="req_test_001"):
            result = await run_in_thread(_read_request_id)
        assert result == "req_test_001"

    @pytest.mark.asyncio
    async def test_propagates_task_id(self) -> None:
        with bind_context(task_id="tk_test_001"):
            result = await run_in_thread(_read_task_id)
        assert result == "tk_test_001"

    @pytest.mark.asyncio
    async def test_propagates_all_context_vars(self) -> None:
        with bind_context(request_id="req_x", task_id="tk_x", operation="op_x", actor="admin"):
            ctx = await run_in_thread(current_context)
        assert ctx == {
            "request_id": "req_x",
            "task_id": "tk_x",
            "operation": "op_x",
            "actor": "admin",
        }

    @pytest.mark.asyncio
    async def test_thread_gets_default_when_no_context_set(self) -> None:
        """没有设置请求上下文时，线程内 ContextVar 读到的也是默认 None。"""
        # 确保外层没 request_id
        assert _request_id.get() is None
        result = await run_in_thread(_read_request_id)
        assert result is None


class TestThreadReturnAndException:
    """run_in_thread 正确回传返回值与异常。"""

    @pytest.mark.asyncio
    async def test_returns_value(self) -> None:
        result = await run_in_thread(_return_arg, "hello")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_returns_value_with_kwargs(self) -> None:
        result = await run_in_thread(_return_arg, arg="world")
        assert result == "world"

    @pytest.mark.asyncio
    async def test_propagates_exception(self) -> None:
        def _explode() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await run_in_thread(_explode)


class TestContextIsolation:
    """不同 run_in_thread 调用之间上下文互不污染。"""

    @pytest.mark.asyncio
    async def test_different_contexts_per_call(self) -> None:
        async def call_in_thread(rid: str) -> str | None:
            with bind_context(request_id=rid):
                return await run_in_thread(_read_request_id)

        r1 = await call_in_thread("req_a")
        r2 = await call_in_thread("req_b")
        assert r1 == "req_a"
        assert r2 == "req_b"

    @pytest.mark.asyncio
    async def test_context_not_leaked_between_calls(self) -> None:
        """线程池线程结束后，下一个任务不应看到上一个的 ContextVar。"""
        with bind_context(request_id="req_first"):
            await run_in_thread(_read_request_id)

        # 外面已经退出 with 块，request_id 已经 reset
        result = await run_in_thread(_read_request_id)
        assert result is None


class TestCancellation:
    """run_in_thread 对 asyncio 取消的响应。"""

    @pytest.mark.asyncio
    async def test_cancelled_error_propagated(self) -> None:
        """取消正在等待 to_thread 的任务应抛出 CancelledError。"""

        async def _cancel_me() -> None:
            task = asyncio.current_task()
            assert task is not None

            # 在另一个协程中取消当前任务
            async def _delayer() -> None:
                await asyncio.sleep(0.02)
                task.cancel()

            asyncio.create_task(_delayer())

            def _block() -> None:
                import time

                time.sleep(0.1)

            await run_in_thread(_block)

        with pytest.raises(asyncio.CancelledError):
            await _cancel_me()
