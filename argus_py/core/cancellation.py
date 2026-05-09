"""任务取消/暂停信号量，用于运行中任务的中断协调。"""

from __future__ import annotations

import asyncio


class CancellationToken:
    """轻量任务取消/暂停信号，线程不安全，适用于 asyncio 单线程模型。"""

    def __init__(self) -> None:
        self._cancelled = False
        self._paused = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    async def wait_if_paused(self, interval: float = 0.5) -> None:
        """如果被暂停，阻塞直到恢复或被取消。"""
        while self._paused and not self._cancelled:
            await asyncio.sleep(interval)
