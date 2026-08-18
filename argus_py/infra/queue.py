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
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EnqueueResult:
    """任务入队结果。

    - ``rejected=True``：队列已满、本次未入队（``scheduler_status`` 为 ``"full"``）。
    - ``already_known=True``：任务已在队列或执行中（幂等命中，不重复入队）。
    """

    task_id: str
    scheduler_status: str
    already_known: bool = False
    rejected: bool = False


class TaskQueue:
    """基于 asyncio.Queue 的进程内任务队列。

    容量语义（O-03）
    ----------------
    - ``max_size <= 0`` 表示无界（仅显式开发选项；``serve`` 启动会告警）。
    - 有界时 ``try_enqueue()`` 在锁内原子完成去重与 ``put_nowait``，满载立即
      返回 ``rejected=True``，不会等待空位，也不会把 task_id 留在内存集合。
    - ``_queued_ids`` 是「逻辑排队」集合：task_id → 入队时刻（monotonic）。
      阻塞式 ``enqueue()``（兼容旧调用）在等待空位期间也保留在集合中，因此
      集合大小可能大于缓冲区当前深度；``try_enqueue`` 不存在该情况。

    ⚠️  内存集合（_queued_ids / _active_ids）不与 SQLite tasks.status 同步。
        重启后队列状态清空，参考模块 docstring 了解"重启不重排队"的设计决策。
    """

    def __init__(self, max_size: int = 0) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=max_size)
        # task_id → 入队时刻（time.monotonic()），用于 oldest queued age 指标。
        self._queued_ids: dict[str, float] = {}
        self._active_ids: set[str] = set()
        self._cancelled_ids: set[str] = set()
        self._lock = asyncio.Lock()
        # 累计因队列满载被拒绝的入队次数（O-03 指标）。
        self._rejected_total = 0

    async def try_enqueue(self, task_id: str) -> EnqueueResult:
        """原子、非阻塞入队。队列满载时立即返回 ``rejected=True``。

        整个临界区（去重检查 + ``put_nowait``）在锁内同步完成，没有 await
        点，因此满载时不会把 task_id 残留进 ``_queued_ids``。已入队/执行中的
        任务返回 ``already_known=True``（幂等命中），与队列是否满载无关。
        """
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
            self._queued_ids[task_id] = time.monotonic()
            try:
                self._queue.put_nowait(task_id)
            except asyncio.QueueFull:
                self._queued_ids.pop(task_id, None)
                self._rejected_total += 1
                return EnqueueResult(task_id=task_id, scheduler_status="full", rejected=True)
            return EnqueueResult(task_id=task_id, scheduler_status="queued")

    async def enqueue(self, task_id: str) -> EnqueueResult:
        """将任务加入队列，防止重复入队或重复执行。

        兼容旧语义的阻塞版本：队列满时等待空位。API 提交路径应优先使用
        ``try_enqueue()`` 获得非阻塞的满载失败语义。
        """
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
            self._queued_ids[task_id] = time.monotonic()

        try:
            await self._queue.put(task_id)
        except BaseException:
            async with self._lock:
                self._queued_ids.pop(task_id, None)
            raise
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
                    self._queued_ids.pop(task_id, None)
                    self._queue.task_done()
                    continue
                self._queued_ids.pop(task_id, None)
                self._active_ids.add(task_id)
            return task_id

    async def complete(self, task_id: str | None) -> None:
        """标记队列项处理完成。"""
        if task_id is not None:
            async with self._lock:
                self._active_ids.discard(task_id)
        self._queue.task_done()

    async def request_stop(self, worker_count: int) -> None:
        """向队列投递 Worker 停止信号。

        保持阻塞式 ``put``：队列满载时等待空位即可保证哨兵最终投递，Worker
        继续优雅排空剩余任务；``TaskWorker.stop()`` 用 ``wait_for`` 给本调用
        限时，超时后走取消兜底，不会无限挂起。
        """
        for _ in range(worker_count):
            await self._queue.put(None)

    async def cancel(self, task_id: str) -> bool:
        """取消尚未被 Worker 取走的队列任务。"""
        async with self._lock:
            if task_id not in self._queued_ids:
                return False
            self._queued_ids.pop(task_id, None)
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

    async def metrics(self) -> dict[str, Any]:
        """队列容量与压力指标（O-03）。

        返回 capacity / queued / active / utilization（``queued ÷ capacity``，
        无界时为 0）/ oldest_queued_age_seconds（无排队时为 -1）/
        rejected_total。``counts()`` 保持 ``{"queued", "active"}`` 兼容旧调用方。
        """
        async with self._lock:
            capacity = self._queue.maxsize
            queued = len(self._queued_ids)
            active = len(self._active_ids)
            oldest_age = -1.0
            if queued:
                oldest_age = time.monotonic() - min(self._queued_ids.values())
            utilization = (queued / capacity) if capacity > 0 else 0.0
            return {
                "capacity": capacity,
                "queued": queued,
                "active": active,
                "utilization": utilization,
                "oldest_queued_age_seconds": oldest_age,
                "rejected_total": self._rejected_total,
            }

    async def snapshot_statuses(self) -> dict[str, str]:
        """批量快照当前调度状态，返回 {task_id: status}。"""
        async with self._lock:
            result: dict[str, str] = {}
            for tid in self._active_ids:
                result[tid] = "running"
            for tid in self._queued_ids:
                result[tid] = "queued"
            return result
