"""任务日志与问题记录服务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from argus_py.browser.snapshot import redact_href, redact_sensitive_text, redact_step_params
from argus_py.core.enums import FindingSeverity, FindingType, StepResult
from argus_py.task.models import Finding, Task, TaskLog
from argus_py.task.storage import TaskFileStorage, TaskSQLiteStorage
from argus_py.utils.jsonx import to_jsonable

TaskEventPublisher = Callable[[str, str, dict[str, Any]], None]


class TaskLogService:
    """管理任务步骤日志和问题记录。"""

    def __init__(
        self,
        storage: TaskFileStorage | TaskSQLiteStorage,
        event_publisher: TaskEventPublisher | None,
    ) -> None:
        self.storage = storage
        self.event_publisher = event_publisher

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
        next_step = step_number or resolved.current_step + 1
        log = TaskLog(
            step_number=next_step,
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
        resolved.current_step = max(resolved.current_step, next_step)
        if isinstance(self.storage, TaskSQLiteStorage):
            self.storage.append_log(resolved.task_id, log)
        else:
            self.storage.save(resolved)
        self._publish(
            "task.log",
            resolved,
            {
                "log": _redact_log_payload(log),
                "currentStep": resolved.current_step,
            },
        )
        return resolved

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
        previous_count = resolved.finding_count
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
        resolved.finding_count = previous_count + 1
        if isinstance(self.storage, TaskSQLiteStorage):
            self.storage.append_finding(resolved.task_id, finding)
        else:
            self.storage.save(resolved)
        self._publish(
            "task.finding",
            resolved,
            {
                "finding": _redact_finding_payload(finding),
                "findingCount": resolved.finding_count,
            },
        )
        return resolved

    def _resolve_task(self, task: Task | str) -> Task:
        """接受任务对象或任务 ID，统一还原为任务对象。"""
        if isinstance(task, Task):
            return task
        return self.storage.load(task)

    def _publish(self, event_type: str, task: Task, data: dict[str, Any]) -> None:
        """发布任务事件。"""
        if self.event_publisher is None:
            return
        self.event_publisher(event_type, task.task_id, to_jsonable(data))


def _path_name(path: str | None) -> str | None:
    """对外事件只暴露文件名，不暴露本机路径。"""
    return Path(path).name if path else None


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
