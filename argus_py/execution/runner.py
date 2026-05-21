"""任务执行编排：调度 handler、管理超时、生成报告。"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable

from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.observability.aspect import log_operation
from argus_py.report.generator import ReportGenerator, generate_report_safely
from argus_py.task.event import TaskTimelineService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.log import TaskLogService
from argus_py.task.models import Task
from argus_py.task.read import TaskReadService

logger = logging.getLogger(__name__)

TaskHandler = Callable[[Task], Task | Awaitable[Task | None] | None]


class TaskRunner:
    """单进程任务执行器 — 属 execution 层，跨模块编排。"""

    def __init__(
        self,
        lifecycle: TaskLifecycleService,
        reader: TaskReadService,
        handlers: dict[TaskType, TaskHandler] | None = None,
        report_generator: ReportGenerator | None = None,
        model_config_service: ModelConfigService | None = None,
    ) -> None:
        self.lifecycle = lifecycle
        self.reader = reader
        self.report_generator = report_generator or ReportGenerator()
        self._model_config_service = model_config_service
        self.handlers = handlers if handlers is not None else self._default_handlers()

    def register_handler(self, task_type: TaskType, handler: TaskHandler) -> None:
        """注册指定任务类型的执行处理器。"""
        self.handlers[task_type] = handler

    @log_operation("task.runner.run", task_arg="task")
    async def run(self, task: Task) -> Task:
        """执行任务并管理生命周期。"""
        if task.status is not TaskStatus.PENDING:
            raise TaskError(f"只有 pending 任务可以执行，当前状态：{task.status.value}")

        running_task = self.lifecycle.start_task(task)
        handler = self.handlers.get(running_task.task_type)
        if handler is None:
            await self._handle_no_handler(running_task)
        assert handler is not None

        try:
            result = await asyncio.wait_for(
                self._run_handler(handler, running_task),
                timeout=running_task.timeout_seconds,
            )
        except TimeoutError as exc:
            return await self._handle_timeout(running_task, exc)
        except Exception as exc:
            return await self._handle_exception(running_task, exc)

        return await self._finalize_run(running_task, result)

    async def _run_handler(self, handler: TaskHandler, task: Task) -> Task | None:
        """执行同步或异步任务 handler。"""
        result = handler(task)
        if inspect.isawaitable(result):
            return await result
        return result

    def _default_handlers(self) -> dict[TaskType, TaskHandler]:
        """默认任务类型处理器。"""
        from argus_py.blackbox.runner import BlackboxRunner
        from argus_py.task.storage import TaskSQLiteStorage

        storage = TaskSQLiteStorage()

        return {
            TaskType.BLACKBOX: BlackboxRunner(
                lifecycle=self.lifecycle or TaskLifecycleService(storage, event_publisher=None),
                reader=self.reader or TaskReadService(storage),
                log_service=TaskLogService(storage),
                timeline_service=TaskTimelineService(storage),
                model_config_service=self._model_config_service,
            ).run,
        }

    def _latest_task(self, task: Task) -> Task:
        """从存储中读取最新任务快照。"""
        try:
            return self.reader.get_task(task.task_id)
        except TaskError:
            logger.warning("从存储读取任务快照失败：%s", task.task_id)
            return task

    async def _generate_report(self, task: Task) -> Task:
        """生成任务报告并回写 HTML 报告路径（在 IO 线程执行，不阻塞事件循环）。"""
        return await asyncio.to_thread(
            generate_report_safely, task, self.report_generator, self.lifecycle.save_task
        )

    async def _handle_no_handler(self, task: Task) -> None:
        """无 handler 时标记失败并生成报告。"""
        message = f"任务类型 {task.task_type.value} 尚未注册执行器。"
        task = await self._generate_report(task)
        self.lifecycle.fail_task(task, message)
        raise TaskError(message)

    async def _handle_timeout(self, task: Task, exc: TimeoutError) -> Task:
        """超时处理：已终态则直接报告，否则标记超时。"""
        latest = self._latest_task(task)
        if latest.status is not TaskStatus.RUNNING:
            return await self._generate_report(latest)
        logger.warning("任务超时：%s（%ds）", task.task_id, task.timeout_seconds)
        latest = await self._generate_report(latest)
        timeout_task = self.lifecycle.timeout_task(latest)
        raise TaskError(timeout_task.error_message or "任务执行超时。") from exc

    async def _handle_exception(self, task: Task, exc: Exception) -> Task:
        """异常处理：已终态则直接报告，否则标记失败。"""
        latest = self._latest_task(task)
        if latest.status is not TaskStatus.RUNNING:
            return await self._generate_report(latest)
        logger.exception("任务执行异常：%s", task.task_id)
        latest = await self._generate_report(latest)
        failed_task = self.lifecycle.fail_task(latest, str(exc))
        raise TaskError(failed_task.error_message or "任务执行失败。") from exc

    async def _finalize_run(self, task: Task, result: Task | None) -> Task:
        """最终报告生成：完成未终态的任务并生成报告。

        先生成报告再完成任务，确保 ``task.complete`` 事件携带 ``reportPath``，
        避免前端报告按钮因字段缺失保持禁用状态。
        """
        completed = result or task
        if completed.status is TaskStatus.RUNNING:
            completed = await self._generate_report(completed)
            completed = self.lifecycle.complete_task(completed)
        return completed
