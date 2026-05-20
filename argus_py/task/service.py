"""TaskService 兼容外观层，委托给职责单一的子服务。

.. deprecated::
    使用 ``TaskLifecycleService`` / ``TaskReadService`` / ``TaskLogService`` /
    ``TaskTimelineService`` / ``TraceReadService`` / ``DebugBundleBuilder`` 代替。
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from argus_py.core.cancellation import CancellationToken
from argus_py.core.constants import DEFAULT_MAX_STEPS, DEFAULT_TASK_TIMEOUT_S
from argus_py.core.enums import FindingSeverity, FindingType, StepResult, TaskStatus, TaskType
from argus_py.observability.aspect import log_operation
from argus_py.observability.debug_bundle import DebugBundleBuilder
from argus_py.observability.trace_reader import TraceReadService
from argus_py.task._base import TaskEventPublisher
from argus_py.task.event import TaskTimelineService, _NullTimelineService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.log import TaskLogService
from argus_py.task.models import Task
from argus_py.task.query import TaskQueryService
from argus_py.task.read import TaskReadService
from argus_py.task.storage import TaskFileStorage, TaskSQLiteStorage

__all__ = ["TaskEventPublisher", "TaskService"]


class TaskService:
    """兼容外观：保持原有全部公开方法签名，内部委托给单一职责子服务。

    新代码推荐直接通过 ``service.lifecycle`` / ``service.query`` /
    ``service.log`` / ``service.timeline`` 子服务调用。本 facade 仅为兼容
    存量调用方而保留。
    """

    def __init__(
        self,
        storage: TaskFileStorage | TaskSQLiteStorage | None = None,
        event_publisher: TaskEventPublisher | None = None,
    ) -> None:
        warnings.warn(
            "TaskService is deprecated — inject sub-services directly: "
            "TaskLifecycleService, TaskReadService, TaskLogService, "
            "TaskTimelineService, TraceReadService, DebugBundleBuilder.",
            DeprecationWarning,
            stacklevel=2,
        )
        resolved = storage or TaskSQLiteStorage()
        self.lifecycle = TaskLifecycleService(resolved, event_publisher)
        self.query = TaskQueryService(resolved)
        self.reader: TaskReadService = self.query.reader
        self.trace_reader: TraceReadService = self.query.trace_reader
        self.debug_builder: DebugBundleBuilder = self.query.debug_builder
        self.log = TaskLogService(resolved, event_publisher)
        # 仅 SQLite 后端支持时间线持久化；非 SQLite 后端用 Null Object 占位，
        # 让 facade 与子服务调用方都不再需要写 ``if timeline is None`` 分支。
        self.timeline: TaskTimelineService | _NullTimelineService = (
            TaskTimelineService(resolved, event_publisher)
            if isinstance(resolved, TaskSQLiteStorage)
            else _NullTimelineService()
        )

    async def emit_timeline(
        self,
        task_id: str,
        event_type: str,
        phase: str,
        step_number: int = 0,
        summary: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        """发射时间线事件（存储 + WebSocket 广播）。"""
        await self.timeline.emit(
            task_id=task_id,
            event_type=event_type,
            phase=phase,
            step_number=step_number,
            summary=summary,
            data=data,
        )

    # ── 生命周期 ──

    @log_operation("task.create")
    def create_task(
        self,
        goal: str,
        name: str | None = None,
        start_url: str | None = None,
        task_type: TaskType = TaskType.BLACKBOX,
        project_id: str | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        timeout_seconds: int = DEFAULT_TASK_TIMEOUT_S,
        capture_screenshots: bool = True,
        parameters: dict[str, Any] | None = None,
    ) -> Task:
        return self.lifecycle.create_task(
            goal=goal,
            name=name,
            start_url=start_url,
            task_type=task_type,
            project_id=project_id,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            capture_screenshots=capture_screenshots,
            parameters=parameters,
        )

    @log_operation("task.restart", task_arg="task")
    def restart_task(self, task: Task | str) -> Task:
        return self.lifecycle.restart_task(task)

    def save_task(self, task: Task) -> Task:
        return self.lifecycle.save_task(task)

    @log_operation("task.update", task_arg="task")
    def update_task_info(
        self,
        task: Task | str,
        *,
        goal: str,
        name: str | None,
        start_url: str | None,
        task_type: TaskType,
        project_id: str | None,
        max_steps: int,
        timeout_seconds: int,
        capture_screenshots: bool,
        parameters: dict[str, Any],
    ) -> Task:
        return self.lifecycle.update_task_info(
            task,
            goal=goal,
            name=name,
            start_url=start_url,
            task_type=task_type,
            project_id=project_id,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            capture_screenshots=capture_screenshots,
            parameters=parameters,
        )

    @log_operation("task.delete", task_arg="task")
    def delete_pending_task(self, task: Task | str) -> None:
        return self.lifecycle.delete_pending_task(task)

    @log_operation("task.start", task_arg="task")
    def start_task(self, task: Task | str) -> Task:
        return self.lifecycle.start_task(task)

    @log_operation("task.complete", task_arg="task")
    def complete_task(
        self,
        task: Task | str,
        result_summary: str | None = None,
        report_path: str | None = None,
    ) -> Task:
        return self.lifecycle.complete_task(
            task, result_summary=result_summary, report_path=report_path
        )

    @log_operation("task.fail", task_arg="task")
    def fail_task(self, task: Task | str, error_message: str) -> Task:
        return self.lifecycle.fail_task(task, error_message)

    @log_operation("task.timeout", task_arg="task")
    def timeout_task(self, task: Task | str, error_message: str = "任务执行超时。") -> Task:
        return self.lifecycle.timeout_task(task, error_message)

    @log_operation("task.cancel", task_arg="task")
    def cancel_task(self, task: Task | str) -> Task:
        return self.lifecycle.cancel_task(task)

    def pause_task(self, task: Task | str) -> Task:
        return self.lifecycle.pause_task(task)

    def resume_task(self, task: Task | str) -> Task:
        return self.lifecycle.resume_task(task)

    def update_status(
        self, task: Task, target: TaskStatus, error_message: str | None = None
    ) -> Task:
        return self.lifecycle.update_status(task, target, error_message=error_message)

    def get_cancellation_token(self, task_id: str) -> CancellationToken:
        return self.lifecycle.get_cancellation_token(task_id)

    def remove_cancellation_token(self, task_id: str) -> None:
        return self.lifecycle.remove_cancellation_token(task_id)

    # ── 查询 ──

    def task_exists(self, task_id: str) -> bool:
        return self.query.task_exists(task_id)

    def get_task_status(self, task_id: str) -> TaskStatus | None:
        return self.query.get_task_status(task_id)

    def get_task(self, task_id: str) -> Task:
        return self.query.get_task(task_id)

    def get_latest_task(self, task: Task) -> Task:
        return self.query.get_latest_task(task)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Task]:
        return self.query.list_tasks(
            status=status, project_id=project_id, offset=offset, limit=limit
        )

    def count_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> int:
        return self.query.count_tasks(status=status, project_id=project_id, q=q)

    def count_findings(self) -> int:
        return self.query.count_findings()

    def list_task_summaries(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        q: str | None = None,
    ) -> tuple[list[Task], int]:
        return self.query.list_task_summaries(
            status=status, project_id=project_id, offset=offset, limit=limit, q=q
        )

    # ── 报告 / 追踪 / 调试包 ──

    def resolve_report_path(self, task: Task) -> Path:
        return self.reader.resolve_report_path(task)

    def resolve_screenshot_path(self, task_id: str, filename: str) -> Path:
        return self.reader.resolve_screenshot_path(task_id, filename)

    def list_llm_traces(
        self,
        task_id: str,
        skip: int = 0,
        limit: int = 50,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.trace_reader.list_llm_traces(task_id, skip=skip, limit=limit, trace_id=trace_id)

    def get_llm_trace_detail(self, task_id: str, trace_id: str) -> dict[str, Any] | None:
        return self.trace_reader.get_llm_trace_detail(task_id, trace_id)

    def build_debug_bundle(
        self, task_id: str, task: Task, events: list[dict[str, Any]] | None = None
    ) -> str:
        return self.debug_builder.build(task_id, task, events=events)

    def flush_logs(self) -> None:
        """批量写入缓冲的步骤日志。"""
        self.log.flush_logs()

    async def flush_events(self) -> None:
        """批量写入缓冲的时间线事件。"""
        await self.timeline.flush_events()

    # ── 日志与问题 ──

    def append_log(
        self,
        task: Task | str,
        action: str,
        result: StepResult = StepResult.SUCCESS,
        params: dict[str, Any] | None = None,
        url_before: str | None = None,
        url_after: str | None = None,
        screenshot_path: str | None = None,
        message: str | None = None,
        error: str | None = None,
        error_code: str | None = None,
        step_number: int | None = None,
    ) -> Task:
        return self.log.append_log(
            task,
            action=action,
            result=result,
            params=params,
            url_before=url_before,
            url_after=url_after,
            screenshot_path=screenshot_path,
            message=message,
            error=error,
            error_code=error_code,
            step_number=step_number,
        )

    def append_finding(
        self,
        task: Task | str,
        title: str,
        description: str,
        severity: FindingSeverity = FindingSeverity.INFO,
        finding_type: FindingType = FindingType.FUNCTIONAL,
        url: str | None = None,
        location: str | None = None,
        screenshot_path: str | None = None,
    ) -> Task:
        return self.log.append_finding(
            task,
            title=title,
            description=description,
            severity=severity,
            finding_type=finding_type,
            url=url,
            location=location,
            screenshot_path=screenshot_path,
        )
