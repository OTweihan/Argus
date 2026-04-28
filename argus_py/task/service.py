"""任务服务。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from argus_py.core.enums import FindingSeverity, FindingType, StepResult, TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.task.models import Finding, Task, TaskLog
from argus_py.task.status import assert_transition
from argus_py.task.storage import TaskFileStorage


class TaskService:
    """任务创建和状态更新服务。"""

    def __init__(self, storage: TaskFileStorage | None = None) -> None:
        self.storage = storage or TaskFileStorage()

    def create_task(
        self,
        goal: str,
        start_url: str | None = None,
        task_type: TaskType = TaskType.BLACKBOX,
        project_id: str | None = None,
        max_steps: int = 20,
        timeout_seconds: int = 300,
        capture_screenshots: bool = True,
        parameters: dict[str, Any] | None = None,
    ) -> Task:
        """创建任务并保存初始快照。"""
        task = Task(
            goal=goal,
            start_url=start_url,
            task_type=task_type,
            project_id=project_id,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            capture_screenshots=capture_screenshots,
            parameters=parameters or {},
        )
        self.storage.save(task)
        return task

    def get_task(self, task_id: str) -> Task:
        """按 ID 获取任务。"""
        if not self.storage.exists(task_id):
            raise TaskError(f"Task not found: {task_id}")
        return self.storage.load(task_id)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
    ) -> list[Task]:
        """列出任务，可按状态和项目过滤。"""
        tasks = self.storage.list_tasks()
        if status is not None:
            tasks = [task for task in tasks if task.status is status]
        if project_id is not None:
            tasks = [task for task in tasks if task.project_id == project_id]
        return tasks

    def save_task(self, task: Task) -> Task:
        """保存任务当前快照。"""
        self.storage.save(task)
        return task

    def _resolve_task(self, task: Task | str) -> Task:
        """接受任务对象或任务 ID，统一还原为任务对象。"""
        if isinstance(task, Task):
            return task
        return self.get_task(task)

    def update_status(self, task: Task, target: TaskStatus, error_message: str | None = None) -> Task:
        """更新任务状态。"""
        assert_transition(task.status, target)
        now = datetime.now(timezone.utc)
        if target is TaskStatus.RUNNING:
            task.started_at = now
        if target in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED}:
            task.completed_at = now
        task.status = target
        task.error_message = error_message
        self.storage.save(task)
        return task

    def start_task(self, task: Task | str) -> Task:
        """将任务标记为运行中。"""
        return self.update_status(self._resolve_task(task), TaskStatus.RUNNING)

    def complete_task(
        self,
        task: Task | str,
        result_summary: str | None = None,
        report_path: str | None = None,
    ) -> Task:
        """将任务标记为完成。"""
        resolved = self._resolve_task(task)
        if result_summary is not None:
            resolved.result_summary = result_summary
        if report_path is not None:
            resolved.report_path = report_path
        return self.update_status(resolved, TaskStatus.COMPLETED)

    def fail_task(self, task: Task | str, error_message: str) -> Task:
        """将任务标记为失败。"""
        return self.update_status(self._resolve_task(task), TaskStatus.FAILED, error_message)

    def timeout_task(self, task: Task | str, error_message: str = "任务执行超时。") -> Task:
        """将任务标记为超时。"""
        return self.update_status(self._resolve_task(task), TaskStatus.TIMEOUT, error_message)

    def cancel_task(self, task: Task | str) -> Task:
        """将任务标记为取消。"""
        return self.update_status(self._resolve_task(task), TaskStatus.CANCELLED)

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
        step_number: int | None = None,
    ) -> Task:
        """追加任务步骤日志并保存。"""
        resolved = self._resolve_task(task)
        log = TaskLog(
            step_number=step_number or resolved.current_step + 1,
            action=action,
            result=result,
            params=params or {},
            url_before=url_before,
            url_after=url_after,
            screenshot_path=screenshot_path,
            message=message,
            error=error,
        )
        resolved.logs.append(log)
        return self.save_task(resolved)

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
        """追加问题记录并保存。"""
        resolved = self._resolve_task(task)
        finding = Finding(
            title=title,
            description=description,
            severity=severity,
            finding_type=finding_type,
            url=url,
            location=location,
            screenshot_path=screenshot_path,
        )
        resolved.findings.append(finding)
        return self.save_task(resolved)
