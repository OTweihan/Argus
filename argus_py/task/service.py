"""TaskService 兼容外观层，委托给职责单一的子服务。"""

from __future__ import annotations

from typing import Any, Callable

from argus_py.core.cancellation import CancellationToken
from argus_py.core.enums import FindingSeverity, FindingType, StepResult, TaskStatus, TaskType
from argus_py.observability.aspect import log_operation
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.log import TaskLogService
from argus_py.task.models import Task
from argus_py.task.query import TaskQueryService
from argus_py.task.storage import TaskFileStorage, TaskSQLiteStorage

TaskEventPublisher = Callable[[str, str, dict[str, Any]], None]


class TaskService:
    """兼容外观：保持原有全部公开方法签名，内部委托给单一职责子服务。"""

    def __init__(
        self,
        storage: TaskFileStorage | TaskSQLiteStorage | None = None,
        event_publisher: TaskEventPublisher | None = None,
    ) -> None:
        resolved = storage or TaskSQLiteStorage()
        self.lifecycle = TaskLifecycleService(resolved, event_publisher)
        self.query = TaskQueryService(resolved)
        self.log = TaskLogService(resolved, event_publisher)

    # ── 生命周期 ──

    @log_operation("task.create")
    def create_task(
        self,
        goal: str,
        name: str | None = None,
        start_url: str | None = None,
        task_type: TaskType = TaskType.BLACKBOX,
        project_id: str | None = None,
        max_steps: int = 20,
        timeout_seconds: int = 300,
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

    def list_task_summaries(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        q: str | None = None,
    ) -> list[Task]:
        return self.query.list_task_summaries(
            status=status, project_id=project_id, offset=offset, limit=limit, q=q
        )

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
