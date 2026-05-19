"""进程内任务队列。

设计约束
--------
- ``_queued_ids`` / ``_active_ids`` / ``_cancelled_ids`` 三个集合仅存在于
  内存中，SQLite 没有对应的队列状态表。
- 服务重启后这些集合全部丢失，新的 ``TaskQueue`` 实例从空状态开始。SQLite
  中 ``status != "running"`` 的任务维持原状（PENDING 的仍是 PENDING）。
- **这是有意设计：重启不重排队。** 崩溃前已入队但尚未被 Worker 消费的任务，
  重启后保留为 ``PENDING`` 状态，用户可手动重新启动。
- 若未来需要自动恢复入队，需在 SQLite 中新增 ``task_queue`` 表持久化队列
  顺序和状态，并在 ``recover_interrupted_tasks`` 中从该表重建队列。
"""

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
    """基于 asyncio.Queue 的进程内任务队列。

    ⚠️  内存集合（_queued_ids / _active_ids）不与 SQLite tasks.status 同步。
        重启后队列状态清空，参考模块 docstring 了解"重启不重排队"的设计决策。
    """

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

    async def counts(self) -> dict[str, int]:
        """持锁返回队列深度。"""
        async with self._lock:
            return {"queued": len(self._queued_ids), "active": len(self._active_ids)}

    async def snapshot_statuses(self) -> dict[str, str]:
        """批量快照当前调度状态，返回 {task_id: status}。"""
        async with self._lock:
            result: dict[str, str] = {}
            for tid in self._active_ids:
                result[tid] = "running"
            for tid in self._queued_ids:
                result[tid] = "queued"
            return result

    async def is_known(self, task_id: str) -> bool:
        """判断任务是否已入队或正在执行。"""
        return (await self.scheduler_status(task_id)) is not None
