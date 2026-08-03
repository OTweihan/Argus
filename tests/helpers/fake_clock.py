"""Fake Clock — 可注入的 monotonic clock 和 sleeper。

供轮询/超时/CAS 租约/进程恢复测试使用，避免真实 asyncio.sleep()
导致的慢测试和 CI 抖动。

使用方式::

    from tests.helpers.fake_clock import FakeClock, FakeSleeper

    clock = FakeClock(initial=0.0)
    sleeper = FakeSleeper()

    # 注入到被测组件
    runner = WhiteboxRunner(..., _monotonic=clock.monotonic, _sleep=sleeper.sleep)

    # 推进时间
    clock.advance(10.0)  # 模拟 10 秒流逝

    # 验证 sleep 调用
    assert sleeper.total_slept >= 5.0
"""

from __future__ import annotations

import asyncio


class FakeClock:
    """可控制的 monotonic clock。"""

    def __init__(self, initial: float = 0.0) -> None:
        self._now = initial

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        """推进时间。"""
        if seconds < 0:
            raise ValueError("不能回退时间")
        self._now += seconds

    def set(self, value: float) -> None:
        """直接设置当前时间值。"""
        self._now = value


class FakeSleeper:
    """可控制的异步 sleeper。

    调用 sleep() 会记录但不实际等待，时间由 FakeClock 推进触发。
    适合测试轮询/退避计数/取消检测等场景。

    限制：sleep() 瞬间完成（仅 asyncio.sleep(0)），因此 ``asyncio.wait_for``
    不会基于 sleep 触发 TimeoutError。如需测试 deadline 超时，应在 sleep()
    返回后检查 FakeClock.monotonic() 与 deadline 的关系，或使用
    advance_until_deadline() 辅助方法。
    """

    def __init__(self, clock: FakeClock | None = None) -> None:
        self._clock = clock
        self._sleep_calls: list[float] = []
        self._total_slept = 0.0

    async def sleep(self, seconds: float) -> None:
        """模拟异步 sleep——记录调用但不真实等待。"""
        self._sleep_calls.append(seconds)
        self._total_slept += seconds
        if self._clock:
            self._clock.advance(seconds)
        # 让出事件循环，允许其他协程推进
        await asyncio.sleep(0)

    async def advance_until_deadline(self, deadline: float) -> None:
        """推进时钟到 deadline，模拟时间耗尽。

        典型用法::

            clock = FakeClock(initial=0)
            sleeper = FakeSleeper(clock)
            deadline = 30.0  # 任务 deadline

            # 注入到被测组件后
            await sleeper.advance_until_deadline(deadline)
            # 此时 clock.monotonic() >= deadline
        """
        if self._clock is None:
            return
        remaining = deadline - self._clock.monotonic()
        if remaining > 0:
            self._clock.advance(remaining)
            self._sleep_calls.append(remaining)
            self._total_slept += remaining
        await asyncio.sleep(0)

    @property
    def total_slept(self) -> float:
        return self._total_slept

    @property
    def call_count(self) -> int:
        return len(self._sleep_calls)

    @property
    def calls(self) -> list[float]:
        return list(self._sleep_calls)

    def reset(self) -> None:
        self._sleep_calls.clear()
        self._total_slept = 0.0
