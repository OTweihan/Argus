"""后台任务 Worker。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from typing import Any

from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.execution.runner import TaskHandler, TaskRunner
from argus_py.infra.queue import TaskQueue
from argus_py.observability.aspect import log_operation
from argus_py.observability.context import run_in_thread
from argus_py.report.generator import ReportGenerator
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.read import TaskReadService
from argus_py.whitebox.client import WhiteboxClient
from argus_py.whitebox.recovery import (
    find_stale_whitebox_tasks,
    reconcile_orphan_whitebox_jobs,
)

logger = logging.getLogger(__name__)

_HANDLER_TYPE = dict[
    TaskType,
    Callable[..., Any],
]

# 最多保留最近几次 Worker loop 未处理异常，供 readiness/诊断查询。
_MAX_CRASH_RECORDS = 3


@dataclass(frozen=True)
class WorkerHealthSnapshot:
    """Worker 真实健康快照，供 ``/ready`` 与 ``/metrics`` 读取。

    ``is_started`` 只是"已调用过 start()"，不能证明 loop 仍在运行——
    loop 可能已异常退出。因此快照额外给出存活 loop 数、异常结束数和最近一次
    消费时间，探针据此判断 Worker 是否真的在消费任务。
    """

    is_started: bool
    total_loops: int  # 累计创建的 Worker loop task 数
    alive_loops: int  # 当前仍在运行的 loop 数
    exited_loops: int  # 正常/被取消退出的 loop 数
    crashed_loops: int  # 未处理异常退出的 loop 数
    last_consume_at: float | None  # monotonic() 时间戳，None 表示从未消费
    recent_crashes: tuple[dict[str, Any], ...] = field(default_factory=tuple)


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
        report_generator: ReportGenerator | None = None,
        worker_id: str = "",
        whitebox_client: WhiteboxClient | None = None,
    ) -> None:
        self.queue = queue
        self._lifecycle = lifecycle
        self._reader = reader
        self._handlers = handlers
        self._model_config_service = model_config_service
        self._report_generator = report_generator
        self._worker_id = worker_id
        # O-04 启动恢复：非空时接管孤儿白盒作业；为空回退原 FAILED 语义。
        self._whitebox_client = whitebox_client
        self.concurrency = max(1, concurrency)
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False
        self._stopped = False
        # ── 健康快照（见 WorkerHealthSnapshot）──
        self._loop_total = 0
        self._loop_alive = 0
        self._loop_exited = 0
        self._loop_crashed = 0
        self._last_consume_at: float | None = None
        self._recent_crashes: deque[dict[str, Any]] = deque(maxlen=_MAX_CRASH_RECORDS)

    @property
    def is_started(self) -> bool:
        """Worker 是否已启动。"""
        return self._started

    def health_snapshot(self) -> WorkerHealthSnapshot:
        """返回 Worker 真实健康快照。

        与 ``is_started`` 布尔标志的区别：loop 异常退出后 ``_started`` 仍为
        True，但 ``alive_loops`` 会归零、``crashed_loops`` 增加。readiness 应
        依据快照判断，而不是只看 ``is_started``。
        """
        return WorkerHealthSnapshot(
            is_started=self._started,
            total_loops=self._loop_total,
            alive_loops=self._loop_alive,
            exited_loops=self._loop_exited,
            crashed_loops=self._loop_crashed,
            last_consume_at=self._last_consume_at,
            recent_crashes=tuple(self._recent_crashes),
        )

    async def start(self) -> None:
        """启动后台 Worker（含 reconciliation）。"""
        if self._started:
            return
        self._started = True

        # 扫描并处理 stale WHITEBOX+RUNNING 任务
        await self._reconcile_stale_tasks()

        self._loop_total += self.concurrency
        self._loop_alive += self.concurrency
        self._tasks = []
        for index in range(self.concurrency):
            task = asyncio.create_task(self._run_loop(index), name=f"argus-worker-{index}")
            # done callback 统计异常退出，供 readiness/探针判断真实存活。
            task.add_done_callback(partial(self._on_loop_done, index=index))
            self._tasks.append(task)

    def _on_loop_done(self, task: asyncio.Task[None], index: int) -> None:
        """Worker loop 结束回调：维护存活/退出/异常计数。

        被取消（shutdown 时 ``stop()`` 的 cancel）视为正常退出；只有带着未处理
        异常结束才计入 ``crashed`` 并记录诊断信息。
        """
        self._loop_alive = max(0, self._loop_alive - 1)
        if task.cancelled():
            self._loop_exited += 1
            return
        exc = task.exception()
        if exc is None:
            self._loop_exited += 1
            return
        self._loop_crashed += 1
        self._recent_crashes.append(
            {
                "loop_index": index,
                "exc_type": type(exc).__name__,
                "message": str(exc),
            }
        )
        logger.error("Worker loop 异常退出: index=%d type=%s %s", index, type(exc).__name__, exc)

    async def stop(self, timeout_seconds: float = 5.0) -> None:
        """停止后台 Worker。

        幂等且健壮：即使 ``start()`` 在 reconciliation 阶段失败（未创建任何
        loop task）也应能干净关闭——``asyncio.wait`` 不接受空集合。
        """
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
        if self._tasks:
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
            if task_id is None:
                return
            # 记录最近一次实际消费任务的时间（monotonic），供探针判断存活。
            self._last_consume_at = time.monotonic()
            try:
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
            report_generator=self._report_generator,
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
        """扫描 stale WHITEBOX+RUNNING 任务并重新接管（O-04）或标记 FAILED。

        安全条件：
        1. status=RUNNING / task_type=WHITEBOX / external_job_id IS NOT NULL
        2. worker_lease_expires_at < now（租约已过期）
        3. CAS 更新防止竞态

        配置了 whitebox_client 时走「完整接管」：查询远端作业状态后重新接管
        （SUCCEEDED 拉结果落 COMPLETED / RUNNING 重置 PENDING 重入队 / 终态落对应
        终态），不再静默遗留孤儿作业。未配置（测试/最小配置）回退原 FAILED 语义。
        """
        # 使用 lifecycle 关联的 storage 获取 pool
        from argus_py.task.storage import TaskSQLiteStorage

        storage = self._lifecycle.storage
        if not isinstance(storage, TaskSQLiteStorage):
            return

        if self._whitebox_client is not None:
            await reconcile_orphan_whitebox_jobs(
                storage=storage,
                lifecycle=self._lifecycle,
                queue=self.queue,
                client=self._whitebox_client,
            )
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        rows = find_stale_whitebox_tasks(storage)

        for row in rows:
            task_id = row["task_id"]
            # CAS: 只有状态、worker_id、lease 全部匹配才更新
            updated = storage.mark_stale_task_terminal(
                task_id,
                TaskStatus.FAILED,
                now_iso,
                f"Worker 重启，远端作业 {row['external_job_id']} "
                f"租约已过期（最后轮询: {row['lease']}）",
                expected_worker_id=row["w_id"],
                expected_lease=row["lease"],
            )
            if not updated:
                continue  # 已被其他逻辑标记为终态

            logger.warning(
                "已标记中断任务: %s (job=%s, status=%s)",
                task_id,
                row["external_job_id"],
                row["external_job_status"],
            )
