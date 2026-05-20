"""任务日志与问题记录服务。"""

from __future__ import annotations

import threading
from typing import Any

from argus_py.core.enums import FindingSeverity, FindingType, StepResult
from argus_py.redaction import redact_finding_entry, redact_log_entry
from argus_py.task._base import TaskEventPublisher, _StorageEventBase
from argus_py.task.models import Finding, Task, TaskLog
from argus_py.task.storage import TaskFileStorage, TaskSQLiteStorage
from argus_py.utils.jsonx import to_jsonable

__all__ = ["TaskEventPublisher", "TaskLogService"]


class TaskLogService(_StorageEventBase):
    """管理任务步骤日志和问题记录。"""

    _LOG_BUFFER_THRESHOLD = 10

    def __init__(
        self,
        storage: TaskFileStorage | TaskSQLiteStorage,
        event_publisher: TaskEventPublisher | None = None,
    ) -> None:
        super().__init__(storage, event_publisher)
        self._pending_logs: list[tuple[str, TaskLog]] = []
        self._flush_lock = threading.Lock()

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
        self._pending_logs.append((resolved.task_id, log))
        self._publish(
            "task.log",
            resolved,
            {
                "log": _redact_log_payload(log),
                "currentStep": resolved.current_step,
            },
        )
        # FileStorage 无增量追加，立即保存全量 task；SQLite 走缓冲批量写入
        if not isinstance(self.storage, TaskSQLiteStorage):
            self.storage.save(resolved)
        elif len(self._pending_logs) >= self._LOG_BUFFER_THRESHOLD:
            self.flush_logs()
        return resolved

    def flush_logs(self) -> None:
        """将缓冲的日志批量写入存储（单事务 executemany）。"""
        with self._flush_lock:
            if not self._pending_logs:
                return
            entries = self._pending_logs[:]
            self._pending_logs.clear()
        if isinstance(self.storage, TaskSQLiteStorage):
            self.storage.append_log_batch(entries)

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


def _redact_log_payload(log: TaskLog) -> dict[str, Any]:
    """生成用于事件推送的脱敏日志。"""
    return redact_log_entry(to_jsonable(log))


def _redact_finding_payload(finding: Finding) -> dict[str, Any]:
    """生成用于事件推送的脱敏问题记录。"""
    return redact_finding_entry(to_jsonable(finding))
