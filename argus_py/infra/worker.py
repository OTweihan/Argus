"""后台任务 Worker。"""

from __future__ import annotations

import asyncio
import logging

from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import TaskError
from argus_py.execution.runner import TaskRunner
from argus_py.infra.queue import TaskQueue
from argus_py.observability.aspect import log_operation
from argus_py.task.service import TaskService

logger = logging.getLogger(__name__)


class TaskWorker:
    """消费任务队列并执行任务。"""

    def __init__(
        self,
        queue: TaskQueue,
        service: TaskService | None = None,
        concurrency: int = 1,
    ) -> None:
        self.queue = queue
        self.service = service or TaskService()
        self.concurrency = max(1, concurrency)
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False

    @property
    def is_started(self) -> bool:
        """Worker 是否已启动。"""
        return self._started

    async def start(self) -> None:
        """启动后台 Worker。"""
        if self._started:
            return
        self._started = True
        self._tasks = [
            asyncio.create_task(self._run_loop(index), name=f"argus-worker-{index}")
            for index in range(self.concurrency)
        ]

    async def stop(self, timeout_seconds: float = 5.0) -> None:
        """停止后台 Worker。"""
        if not self._started:
            return
        await self.queue.request_stop(len(self._tasks))
        done, pending = await asyncio.wait(self._tasks, timeout=timeout_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.gather(*done, return_exceptions=True)
        self._tasks = []
        self._started = False

    async def _run_loop(self, index: int) -> None:
        """Worker 主循环。"""
        while True:
            task_id = await self.queue.get()
            try:
                if task_id is None:
                    return
                await self._run_task(task_id)
            finally:
                await self.queue.complete(task_id)

    @log_operation("task.worker.run", task_arg="task_id")
    async def _run_task(self, task_id: str) -> None:
        """执行单个任务。"""
        try:
            task = self.service.get_task(task_id)
        except TaskError:
            logger.warning("Worker 获取任务失败：%s", task_id)
            return

        if task.status is not TaskStatus.PENDING:
            return

        runner = TaskRunner(service=self.service)
        try:
            await runner.run(task)
        except TaskError:
            logger.warning("任务执行失败：%s", task_id)
            return
        except Exception as exc:
            logger.exception("任务执行异常：%s", task_id)
            latest = self.service.get_latest_task(task)
            if latest.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                self.service.fail_task(latest, str(exc))
