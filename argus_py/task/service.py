"""任务服务。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from argus_py.browser.snapshot import redact_href, redact_sensitive_text, redact_step_params
from argus_py.core.enums import FindingSeverity, FindingType, StepResult, TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.task.models import Finding, Task, TaskLog
from argus_py.task.status import assert_transition
from argus_py.task.storage import TaskFileStorage
from argus_py.utils.jsonx import to_jsonable

TaskEventPublisher = Callable[[str, str, dict[str, Any]], None]


class TaskService:
    """任务创建和状态更新服务。"""

    def __init__(
        self,
        storage: TaskFileStorage | None = None,
        event_publisher: TaskEventPublisher | None = None,
    ) -> None:
        self.storage = storage or TaskFileStorage()
        self.event_publisher = event_publisher

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
        self._publish("task.created", task, {"task": _task_summary(task)})
        return task

    def get_task(self, task_id: str) -> Task:
        """按 ID 获取任务。"""
        if not self.storage.exists(task_id):
            raise TaskError(f"Task not found: {task_id}")
        return self.storage.load(task_id)

    def get_latest_task(self, task: Task) -> Task:
        """从存储中读取最新任务快照，失败时返回原对象。"""
        try:
            return self.get_task(task.task_id)
        except Exception:
            return task

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Task]:
        """列出任务，可按状态和项目过滤，支持分页。"""
        has_filter = status is not None or project_id is not None
        if has_filter:
            tasks = self.storage.list_tasks()
            if status is not None:
                tasks = [task for task in tasks if task.status is status]
            if project_id is not None:
                tasks = [task for task in tasks if task.project_id == project_id]
            if offset:
                tasks = tasks[offset:]
            if limit is not None:
                tasks = tasks[:limit]
            return tasks
        return self.storage.list_tasks(offset=offset, limit=limit)

    def count_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
    ) -> int:
        """返回任务总数。无过滤条件时只列文件名避免全量反序列化。"""
        if status is None and project_id is None:
            return self.storage.count_tasks()
        return len(self.list_tasks(status=status, project_id=project_id))

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
        previous_status = task.status
        now = datetime.now(timezone.utc)
        if target is TaskStatus.RUNNING:
            task.started_at = now
        if target in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED}:
            task.completed_at = now
        task.status = target
        task.error_message = error_message
        self.storage.save(task)
        self._publish(
            "task.status",
            task,
            {
                "previousStatus": previous_status.value,
                "status": target.value,
                "errorMessage": error_message,
                "task": _task_summary(task),
            },
        )
        if target in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.TIMEOUT,
            TaskStatus.CANCELLED,
        }:
            self._publish(
                "task.complete",
                task,
                {
                    "status": target.value,
                    "resultSummary": _redact_optional_text(task.result_summary),
                    "errorMessage": _redact_optional_text(task.error_message),
                    "reportPath": _path_name(task.report_path),
                    "task": _task_summary(task),
                },
            )
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
        error_code: str | None = None,
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
            error_code=error_code,
        )
        resolved.logs.append(log)
        saved = self.save_task(resolved)
        self._publish(
            "task.log",
            saved,
            {
                "log": _redact_log_payload(log),
                "currentStep": saved.current_step,
            },
        )
        return saved

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
        saved = self.save_task(resolved)
        self._publish(
            "task.finding",
            saved,
            {
                "finding": _redact_finding_payload(finding),
                "findingCount": len(saved.findings),
            },
        )
        return saved

    def _publish(self, event_type: str, task: Task, data: dict[str, Any]) -> None:
        """发布任务事件。"""
        if self.event_publisher is None:
            return
        self.event_publisher(event_type, task.task_id, to_jsonable(data))


def _task_summary(task: Task) -> dict[str, Any]:
    """生成轻量任务摘要，避免每个事件重复携带完整日志。"""
    return {
        "taskId": task.task_id,
        "projectId": task.project_id,
        "goal": redact_sensitive_text(task.goal),
        "startUrl": redact_href(task.start_url) if task.start_url else None,
        "taskType": task.task_type.value,
        "status": task.status.value,
        "currentStep": task.current_step,
        "findingCount": len(task.findings),
        "reportPath": _path_name(task.report_path),
        "resultSummary": _redact_optional_text(task.result_summary),
        "errorMessage": _redact_optional_text(task.error_message),
    }


def _path_name(path: str | None) -> str | None:
    """对外事件只暴露文件名，不暴露本机路径。"""
    return Path(path).name if path else None


def _redact_optional_text(text: str | None) -> str | None:
    """脱敏可选文本。"""
    return redact_sensitive_text(text) if text else None


def _redact_log_payload(log: TaskLog) -> dict[str, Any]:
    """生成用于事件推送的脱敏日志。"""
    data = to_jsonable(log)
    params = data.get("params")
    if isinstance(params, dict):
        data["params"] = redact_step_params(params)
    for url_key in ("url_before", "url_after"):
        value = data.get(url_key)
        if isinstance(value, str):
            data[url_key] = redact_href(value)
    data["screenshot_path"] = _path_name(data.get("screenshot_path"))
    for text_key in ("message", "error"):
        value = data.get(text_key)
        if isinstance(value, str):
            data[text_key] = redact_sensitive_text(value)
    return data


def _redact_finding_payload(finding: Finding) -> dict[str, Any]:
    """生成用于事件推送的脱敏问题记录。"""
    data = to_jsonable(finding)
    url = data.get("url")
    if isinstance(url, str):
        data["url"] = redact_href(url)
    data["screenshot_path"] = _path_name(data.get("screenshot_path"))
    for text_key in ("title", "description", "location"):
        value = data.get(text_key)
        if isinstance(value, str):
            data[text_key] = redact_sensitive_text(value)
    return data
