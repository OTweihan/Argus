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

# handler 收窄为 async-only：返回 ``Awaitable[Task | None]``。
# 同步扩展必须由调用方经 run_in_thread 包装后再注册，避免阻塞事件循环。
TaskHandler = Callable[[Task], Awaitable[Task | None]]

# 终态集合（重复写入保护）
TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.CANCELLED,
    }
)

# handler 返回全新 Task 快照时，以下生命周期/身份字段一律从最新持久化状态回填，
# 不采纳快照值——防止覆盖外部 cancel/pause 写入的状态、丢失租约/时间戳/重试链信息。
# 注意：logs/result_json/source_*/external_job_* 等半结果字段不在此列，既不会从快照
# 采纳（全新 Task() 默认空），也不会被回填；快照型 handler 如需保留这些字段，应在返回
# 快照前自行携带。字段清单需与 task/models.Task 保持同步，新增生命周期字段时需一并维护。
_LIFECYCLE_FIELDS: frozenset[str] = frozenset(
    {
        "task_id",
        "status",
        "created_at",
        "started_at",
        "completed_at",
        "worker_id",
        "worker_lease_expires_at",
        "execution_attempt",
        "retry_parent_task_id",
        "name",
        "project_id",
        "goal",
        "start_url",
        "task_type",
        "max_steps",
        "timeout_seconds",
        "capture_screenshots",
        "parameters",
        "whitebox_config_json",
        "whitebox_config_schema_version",
    }
)


class TaskRunner:
    """单进程任务执行器 — 属 execution 层，跨模块编排。

    Handlers 与报告生成器由组合根注入（必需），实例可跨任务复用。
    TaskRunner 是任务终态的唯一写入者。Handler 通过类型化异常表达结果。
    """

    def __init__(
        self,
        lifecycle: TaskLifecycleService,
        handlers: dict[TaskType, TaskHandler],
        report_generator: ReportGenerator,
        worker_id: str = "",
    ) -> None:
        self.lifecycle = lifecycle
        self.handlers = handlers
        self.report_generator = report_generator
        self._worker_id = worker_id

    def register_handler(self, task_type: TaskType, handler: TaskHandler) -> None:
        """注册指定任务类型的执行处理器。"""
        self.handlers[task_type] = handler

    @log_operation("task.runner.run", task_arg="task")
    async def run(self, task: Task) -> Task:
        """执行任务并管理生命周期。

        Handler 返回值语义：
        - 返回全新 Task 快照 → 采纳其 result_summary/findings 等结果字段进入报告与终态，
          生命周期/身份字段以最新持久化状态为准；
        - 返回 None 或原地返回同一对象 → 以运行期 task 对象（含 handler 原地修改）为准。
        完成前再次核对最新持久化状态，外部 cancel/pause 写入的终态不会被迟到的成功返回覆盖。

        终态写入规则：
        - Handler 正常返回 → COMPLETED（除非外部已写入终态）
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

        handler_result: Task | None = None
        try:
            handler_result = await asyncio.wait_for(
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

        return await self._finalize_run(running_task, handler_result)

    async def _run_handler(self, handler: TaskHandler, task: Task) -> Task | None:
        """执行异步任务 handler。

        TaskHandler 收窄为 async-only：同步 handler 会被拦截并给出明确错误，
        同步扩展必须由调用方经 run_in_thread 包装后再注册，避免阻塞事件循环。
        类型化异常直接透传到 run() 的 except 链。
        """
        result = handler(task)
        if not inspect.isawaitable(result):
            raise TypeError(
                f"TaskHandler 必须是异步 handler（当前返回 {type(result).__name__}），"
                "同步实现请用 run_in_thread 包装后再注册。"
            )
        return await result

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
        """最终报告生成：完成未终态的任务并生成报告。

        数据源优先级：
        - handler 返回全新 Task 快照 → 以其为结果数据源，生命周期/身份字段从
          最新持久化状态回填（见 _LIFECYCLE_FIELDS）；
        - 返回 None 或原地返回同一对象 → 以运行期 task 对象（含 handler 原地修改）为准。
        完成前读取最新持久化状态：已写入终态（外部取消/并发终态）或非 RUNNING
        （外部 pause）时原样返回、绝不覆盖；报告生成后再核对一次，防止迟到的
        成功返回覆盖外部取消。
        """
        latest = self._latest_task(task)
        if latest.status in TERMINAL_STATUSES:
            # 外部/并发已写入终态：不覆盖
            return latest
        if latest.status is not TaskStatus.RUNNING:
            # 外部 pause 已介入：保留非运行状态，不推进完成
            return latest
        if result is not None and result is not task:
            completed = result
            for field in _LIFECYCLE_FIELDS:
                setattr(completed, field, getattr(latest, field))
        else:
            completed = task
        completed = await self._generate_report(completed)
        # 报告生成期间外部可能已取消/暂停，完成前再次核对最新状态
        final = self._latest_task(task)
        if final.status is not TaskStatus.RUNNING:
            return final
        return self.lifecycle.complete_task(completed)


# ── whitebox 类型化异常导入 ──────────────────────────────────────────────
# 放在模块底部以避免循环导入，同时让 run() 的 except 链可用

from argus_py.whitebox.exceptions import (  # noqa: E402
    WhiteboxTaskCancelled,
    WhiteboxTaskError,
    WhiteboxTaskTimeout,
)
