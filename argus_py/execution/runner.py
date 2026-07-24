"""任务执行编排：调度 handler、管理超时、生成报告。"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable

from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.observability.aspect import log_operation
from argus_py.observability.context import run_in_thread
from argus_py.report.generator import ReportGenerator, generate_report_safely
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.models import Task

logger = logging.getLogger(__name__)

TaskHandler = Callable[[Task], Task | Awaitable[Task | None] | None]

# 终态集合（重复写入保护）
TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.CANCELLED,
    }
)


class TaskRunner:
    """单进程任务执行器 — 属 execution 层，跨模块编排。

    Handlers 由组合根注入（必需）。TaskRunner 是任务终态的唯一写入者。
    Handler 通过类型化异常表达结果。
    """

    def __init__(
        self,
        lifecycle: TaskLifecycleService,
        handlers: dict[TaskType, TaskHandler],
        report_generator: ReportGenerator | None = None,
        worker_id: str = "",
    ) -> None:
        self.lifecycle = lifecycle
        self.handlers = handlers
        self.report_generator = report_generator or ReportGenerator()
        self._worker_id = worker_id

    def register_handler(self, task_type: TaskType, handler: TaskHandler) -> None:
        """注册指定任务类型的执行处理器。"""
        self.handlers[task_type] = handler

    @log_operation("task.runner.run", task_arg="task")
    async def run(self, task: Task) -> Task:
        """执行任务并管理生命周期。

        终态写入规则：
        - Handler 返回 None（正常完成）→ COMPLETED
        - Handler 抛 WhiteboxTaskCancelled → CANCELLED
        - Handler 抛 WhiteboxTaskTimeout → TIMEOUT
        - Handler 抛 WhiteboxTaskError → FAILED
        - Handler 被 asyncio.wait_for 取消 (TimeoutError) → TIMEOUT（安全熔断）
        """
        if task.status is not TaskStatus.PENDING:
            raise TaskError(f"只有 pending 任务可以执行，当前状态：{task.status.value}")

        running_task = self.lifecycle.start_task(task, worker_id=self._worker_id)
        handler = self.handlers.get(running_task.task_type)
        if handler is None:
            await self._handle_no_handler(running_task)
        assert handler is not None

        # 安全熔断 = task timeout + 30s 余量
        # 正常路径：handler 内部 deadline 先触发
        # 熔断路径：handler 完全失控时 asyncio.wait_for 介入
        safety_timeout = running_task.timeout_seconds + 30

        try:
            await asyncio.wait_for(
                self._run_handler(handler, running_task),
                timeout=safety_timeout,
            )
        except WhiteboxTaskCancelled:
            return await self._handle_cancelled(running_task)
        except WhiteboxTaskTimeout:
            return await self._handle_timeout(running_task)
        except TimeoutError:
            # 安全熔断触发：handler 未在 safety_timeout 内完成
            logger.error("安全熔断触发: %s", running_task.task_id)
            return await self._handle_timeout(running_task)
        except WhiteboxTaskError as exc:
            return await self._handle_exception(running_task, exc)
        except Exception as exc:
            return await self._handle_exception(running_task, exc)

        return await self._finalize_run(running_task)

    async def _run_handler(self, handler: TaskHandler, task: Task) -> Task | None:
        """执行同步或异步任务 handler。

        类型化异常直接透传到 run() 的 except 链。
        """
        result = handler(task)
        if inspect.isawaitable(result):
            return await result
        return result

    # ── 终态处理 ──────────────────────────────────────────────────────────

    async def _handle_cancelled(self, task: Task) -> Task:
        """Handler 检测到取消 → CANCELLED。"""
        latest = self._latest_task(task)
        if latest.status in TERMINAL_STATUSES:
            return await self._generate_report(latest)
        return self.lifecycle.cancel_task(latest)

    async def _handle_timeout(self, task: Task) -> Task:
        """超时 → TIMEOUT。"""
        latest = self._latest_task(task)
        if latest.status in TERMINAL_STATUSES:
            return await self._generate_report(latest)
        logger.warning("任务超时: %s（%ds）", task.task_id, task.timeout_seconds)
        latest = await self._generate_report(latest)
        timeout_task = self.lifecycle.timeout_task(latest)
        raise TaskError(timeout_task.error_message or "任务执行超时。")

    async def _handle_exception(self, task: Task, exc: Exception) -> Task:
        """异常 → FAILED。"""
        latest = self._latest_task(task)
        if latest.status in TERMINAL_STATUSES:
            return await self._generate_report(latest)
        logger.exception("任务执行异常: %s", task.task_id)
        latest = await self._generate_report(latest)
        failed_task = self.lifecycle.fail_task(latest, str(exc))
        raise TaskError(failed_task.error_message or "任务执行失败。") from exc

    # ── 辅助 ──────────────────────────────────────────────────────────────

    def _latest_task(self, task: Task) -> Task:
        """从存储中读取最新任务快照（复用 lifecycle 的 storage 实例）。"""
        try:
            return self.lifecycle.storage.load(task.task_id)
        except TaskError:
            logger.warning("从存储读取任务快照失败: %s", task.task_id)
            return task

    async def _generate_report(self, task: Task) -> Task:
        """生成任务报告并回写 HTML 报告路径。"""
        return await run_in_thread(
            generate_report_safely,
            task,
            self.report_generator,
            self.lifecycle.save_task,
        )

    async def _handle_no_handler(self, task: Task) -> None:
        """无 handler 时标记失败并生成报告。"""
        message = f"任务类型 {task.task_type.value} 尚未注册执行器。"
        task = await self._generate_report(task)
        self.lifecycle.fail_task(task, message)
        raise TaskError(message)

    async def _finalize_run(self, task: Task, result: Task | None = None) -> Task:
        """最终报告生成：完成未终态的任务并生成报告。"""
        completed = result or task
        if completed.status is TaskStatus.RUNNING:
            completed = await self._generate_report(completed)
            completed = self.lifecycle.complete_task(completed)
        return completed


# ── whitebox 类型化异常导入 ──────────────────────────────────────────────
# 放在模块底部以避免循环导入，同时让 run() 的 except 链可用

from argus_py.whitebox.exceptions import (  # noqa: E402
    WhiteboxTaskCancelled,
    WhiteboxTaskError,
    WhiteboxTaskTimeout,
)
