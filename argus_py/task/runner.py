"""任务执行入口。"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable

from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.report.generator import ReportGenerator, generate_report_safely
from argus_py.task.models import Task
from argus_py.task.service import TaskService

logger = logging.getLogger(__name__)

TaskHandler = Callable[[Task], Task | Awaitable[Task | None] | None]


class TaskRunner:
    """单进程任务执行器。"""

    def __init__(
        self,
        service: TaskService | None = None,
        handlers: dict[TaskType, TaskHandler] | None = None,
        report_generator: ReportGenerator | None = None,
    ) -> None:
        self.service = service or TaskService()
        self.report_generator = report_generator or ReportGenerator()
        self.handlers = handlers if handlers is not None else self._default_handlers()

    def register_handler(self, task_type: TaskType, handler: TaskHandler) -> None:
        """注册指定任务类型的执行处理器。"""
        self.handlers[task_type] = handler

    async def run(self, task: Task) -> Task:
        """执行任务并管理生命周期。"""
        if task.status is not TaskStatus.PENDING:
            raise TaskError(f"只有 pending 任务可以执行，当前状态：{task.status.value}")

        running_task = self.service.start_task(task)
        handler = self.handlers.get(running_task.task_type)
        if handler is None:
            message = f"任务类型 {running_task.task_type.value} 尚未注册执行器。"
            failed_task = self.service.fail_task(running_task, message)
            self._generate_report(failed_task)
            raise TaskError(message)

        try:
            result = await asyncio.wait_for(
                self._run_handler(handler, running_task),
                timeout=running_task.timeout_seconds,
            )
        except TimeoutError as exc:
            latest = self._latest_task(running_task)
            if latest.status is not TaskStatus.RUNNING:
                return self._generate_report(latest)
            logger.warning("任务超时：%s（%ds）", running_task.task_id, running_task.timeout_seconds)
            timeout_task = self.service.timeout_task(latest)
            timeout_task = self._generate_report(timeout_task)
            raise TaskError(timeout_task.error_message or "任务执行超时。") from exc
        except Exception as exc:
            latest = self._latest_task(running_task)
            if latest.status is not TaskStatus.RUNNING:
                return self._generate_report(latest)
            logger.exception("任务执行异常：%s", running_task.task_id)
            failed_task = self.service.fail_task(latest, str(exc))
            failed_task = self._generate_report(failed_task)
            raise TaskError(failed_task.error_message or "任务执行失败。") from exc

        completed_task = result or running_task
        if completed_task.status is TaskStatus.RUNNING:
            completed_task = self.service.complete_task(completed_task)
        return self._generate_report(completed_task)

    async def _run_handler(self, handler: TaskHandler, task: Task) -> Task | None:
        """执行同步或异步任务 handler。"""
        result = handler(task)
        if inspect.isawaitable(result):
            return await result
        return result

    def _default_handlers(self) -> dict[TaskType, TaskHandler]:
        """默认任务类型处理器。"""
        from argus_py.blackbox.runner import BlackboxRunner

        return {TaskType.BLACKBOX: BlackboxRunner(service=self.service).run}

    def _latest_task(self, task: Task) -> Task:
        """从存储中读取最新任务快照。"""
        try:
            return self.service.get_task(task.task_id)
        except TaskError:
            logger.warning("从存储读取任务快照失败：%s", task.task_id)
            return task

    def _generate_report(self, task: Task) -> Task:
        """生成任务报告并回写 HTML 报告路径。"""
        return generate_report_safely(task, self.report_generator, self.service.save_task)
