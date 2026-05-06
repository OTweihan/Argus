"""进程内任务队列。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class EnqueueResult:
    """任务入队结果。"""

    task_id: str
    scheduler_status: str
    already_known: bool = False


class TaskQueue:
    """基于 asyncio.Queue 的进程内任务队列。"""

    def __init__(self, max_size: int = 0) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=max_size)
        self._queued_ids: set[str] = set()
        self._active_ids: set[str] = set()
        self._cancelled_ids: set[str] = set()
        self._lock = asyncio.Lock()

    async def enqueue(self, task_id: str) -> EnqueueResult:
        """将任务加入队列，防止重复入队或重复执行。"""
        async with self._lock:
            if task_id in self._active_ids:
                return EnqueueResult(
                    task_id=task_id,
                    scheduler_status="running",
                    already_known=True,
                )
            if task_id in self._queued_ids:
                return EnqueueResult(
                    task_id=task_id,
                    scheduler_status="queued",
                    already_known=True,
                )
            await self._queue.put(task_id)
            self._queued_ids.add(task_id)
            return EnqueueResult(task_id=task_id, scheduler_status="queued")

    async def get(self) -> str | None:
        """获取下一个任务 ID，None 表示停止信号。"""
        while True:
            task_id = await self._queue.get()
            if task_id is None:
                return None
            async with self._lock:
                if task_id in self._cancelled_ids:
                    self._cancelled_ids.discard(task_id)
                    self._queued_ids.discard(task_id)
                    self._queue.task_done()
                    continue
                self._queued_ids.discard(task_id)
                self._active_ids.add(task_id)
            return task_id

    async def complete(self, task_id: str | None) -> None:
        """标记队列项处理完成。"""
        if task_id is not None:
            async with self._lock:
                self._active_ids.discard(task_id)
        self._queue.task_done()

    async def request_stop(self, worker_count: int) -> None:
        """向队列投递 Worker 停止信号。"""
        for _ in range(worker_count):
            await self._queue.put(None)

    async def cancel(self, task_id: str) -> bool:
        """取消尚未被 Worker 取走的队列任务。"""
        async with self._lock:
            if task_id not in self._queued_ids:
                return False
            self._queued_ids.discard(task_id)
            self._cancelled_ids.add(task_id)
            return True

    async def scheduler_status(self, task_id: str) -> str | None:
        """查询调度状态。"""
        async with self._lock:
            if task_id in self._active_ids:
                return "running"
            if task_id in self._queued_ids:
                return "queued"
        return None

    async def is_known(self, task_id: str) -> bool:
        """判断任务是否已入队或正在执行。"""
        return (await self.scheduler_status(task_id)) is not None
