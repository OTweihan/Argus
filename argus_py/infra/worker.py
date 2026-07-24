"""后台任务 Worker。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.execution.runner import TaskHandler, TaskRunner
from argus_py.infra.queue import TaskQueue
from argus_py.observability.aspect import log_operation
from argus_py.observability.context import run_in_thread
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.read import TaskReadService

logger = logging.getLogger(__name__)

_HANDLER_TYPE = dict[
    TaskType,
    Callable[..., Any],
]


class TaskWorker:
    """消费任务队列并执行任务。"""

    def __init__(
        self,
        queue: TaskQueue,
        lifecycle: TaskLifecycleService,
        reader: TaskReadService,
        handlers: dict[TaskType, TaskHandler],
        concurrency: int = 1,
        model_config_service: ModelConfigService | None = None,
        worker_id: str = "",
    ) -> None:
        self.queue = queue
        self._lifecycle = lifecycle
        self._reader = reader
        self._handlers = handlers
        self._model_config_service = model_config_service
        self._worker_id = worker_id
        self.concurrency = max(1, concurrency)
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False
        self._stopped = False

    @property
    def is_started(self) -> bool:
        """Worker 是否已启动。"""
        return self._started

    async def start(self) -> None:
        """启动后台 Worker（含 reconciliation）。"""
        if self._started:
            return
        self._started = True

        # 扫描并处理 stale WHITEBOX+RUNNING 任务
        await self._reconcile_stale_tasks()

        self._tasks = [
            asyncio.create_task(self._run_loop(index), name=f"argus-worker-{index}")
            for index in range(self.concurrency)
        ]

    async def stop(self, timeout_seconds: float = 5.0) -> None:
        """停止后台 Worker。"""
        self._stopped = True
        if not self._started:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, timeout_seconds)
        try:
            await asyncio.wait_for(
                self.queue.request_stop(len(self._tasks)),
                timeout=max(0.0, deadline - loop.time()),
            )
        except TimeoutError:
            logger.warning("Worker 停止信号投递超时，将取消剩余任务")
        done, pending = await asyncio.wait(
            self._tasks,
            timeout=max(0.0, deadline - loop.time()),
        )
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
            task = await run_in_thread(self._reader.get_task, task_id)
        except TaskError:
            logger.warning("Worker 获取任务失败: %s", task_id)
            return

        if task.status is not TaskStatus.PENDING:
            return

        runner = TaskRunner(
            lifecycle=self._lifecycle,
            handlers=self._handlers,
            worker_id=self._worker_id,
        )
        try:
            await runner.run(task)
        except TaskError:
            logger.warning("任务执行失败: %s", task_id)
            return
        except Exception:
            logger.exception("任务执行异常: %s", task_id)
            latest = await run_in_thread(self._reader.get_task, task_id)
            if latest.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                await run_in_thread(self._lifecycle.fail_task, latest, "Worker 异常终止")

    # ── Reconciliation ────────────────────────────────────────────────────

    async def _reconcile_stale_tasks(self) -> None:
        """扫描 stale WHITEBOX+RUNNING 任务并标记为 FAILED。

        安全条件：
        1. status=RUNNING / task_type=WHITEBOX / external_job_id IS NOT NULL
        2. worker_lease_expires_at < now（租约已过期）
        3. CAS 更新防止竞态
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # 使用 lifecycle 关联的 storage 获取 pool
        from argus_py.task.storage import TaskSQLiteStorage

        storage = self._lifecycle.storage
        if not isinstance(storage, TaskSQLiteStorage):
            return

        pool = storage._tasks._pool

        with pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT task_id, external_job_id, external_job_status, "
                "worker_id AS w_id, worker_lease_expires_at AS lease "
                "FROM tasks WHERE status = ? AND task_type = ? "
                "AND external_job_id IS NOT NULL "
                "AND worker_lease_expires_at IS NOT NULL "
                "AND worker_lease_expires_at < ?",
                (
                    TaskStatus.RUNNING.value,
                    TaskType.WHITEBOX.value,
                    now_iso,
                ),
            ).fetchall()

        for row in rows:
            task_id = row["task_id"]
            # CAS: 只有状态、worker_id、lease 全部匹配才更新
            with pool.tx() as conn:
                cursor = conn.execute(
                    "UPDATE tasks SET status = ?, completed_at = ?, "
                    "error_message = ? "
                    "WHERE task_id = ? AND status = ? "
                    "AND worker_id = ? AND worker_lease_expires_at = ?",
                    (
                        TaskStatus.FAILED.value,
                        now_iso,
                        f"Worker 重启，远端作业 {row['external_job_id']} "
                        f"租约已过期（最后轮询: {row['lease']}）",
                        task_id,
                        TaskStatus.RUNNING.value,
                        row["w_id"],
                        row["lease"],
                    ),
                )
                if cursor.rowcount == 0:
                    continue  # 已被其他逻辑标记为终态

            logger.warning(
                "已标记中断任务: %s (job=%s, status=%s)",
                task_id,
                row["external_job_id"],
                row["external_job_status"],
            )
