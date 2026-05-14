"""任务生命周期管理。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from argus_py.core.cancellation import CancellationToken
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.observability import audit
from argus_py.redaction import redact_href, redact_sensitive_text
from argus_py.task._base import TaskEventPublisher, _StorageEventBase
from argus_py.task.models import Task
from argus_py.task.status import assert_transition
from argus_py.task.storage import TaskFileStorage, TaskSQLiteStorage

__all__ = ["TaskEventPublisher", "TaskLifecycleService"]


class TaskLifecycleService(_StorageEventBase):
    """管理任务创建、删除、状态流转和取消令牌。"""

    def __init__(
        self,
        storage: TaskFileStorage | TaskSQLiteStorage,
        event_publisher: TaskEventPublisher | None,
    ) -> None:
        super().__init__(storage, event_publisher)
        self._cancellation_tokens: dict[str, CancellationToken] = {}

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
        """创建任务并保存初始快照。"""
        task = Task(
            goal=goal,
            name=name,
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
        audit("task.create", task_id=task.task_id, task=_task_summary(task))
        return task

    def save_task(self, task: Task) -> Task:
        """保存任务当前快照。"""
        self.storage.save(task)
        return task

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
        """更新待执行任务的基础信息。"""
        resolved = self._resolve_task(task)
        if resolved.status is not TaskStatus.PENDING:
            raise TaskError(f"只有 pending 任务可以编辑，当前状态：{resolved.status.value}。")

        resolved.goal = goal
        resolved.name = name
        resolved.start_url = start_url
        resolved.task_type = task_type
        resolved.project_id = project_id
        resolved.max_steps = max_steps
        resolved.timeout_seconds = timeout_seconds
        resolved.capture_screenshots = capture_screenshots
        resolved.parameters = parameters
        self.storage.save(resolved)
        self._publish("task.updated", resolved, {"task": _task_summary(resolved)})
        audit("task.update", task_id=resolved.task_id, task=_task_summary(resolved))
        return resolved

    def delete_pending_task(self, task: Task | str) -> None:
        """删除未启动的 pending 任务。"""
        resolved = self._resolve_task(task)
        if resolved.status is not TaskStatus.PENDING:
            raise TaskError(f"只有 pending 任务可以删除，当前状态：{resolved.status.value}。")
        self.storage.delete(resolved.task_id)
        self.remove_cancellation_token(resolved.task_id)
        self._publish("task.deleted", resolved, {"taskId": resolved.task_id})
        audit("task.delete", task_id=resolved.task_id)

    def get_cancellation_token(self, task_id: str) -> CancellationToken:
        """获取任务的取消/暂停信号量，懒创建。"""
        if task_id not in self._cancellation_tokens:
            self._cancellation_tokens[task_id] = CancellationToken()
        return self._cancellation_tokens[task_id]

    def remove_cancellation_token(self, task_id: str) -> None:
        """移除任务的取消/暂停信号量。"""
        self._cancellation_tokens.pop(task_id, None)

    def update_status(
        self, task: Task, target: TaskStatus, error_message: str | None = None
    ) -> Task:
        """更新任务状态。"""
        assert_transition(task.status, target)
        previous_status = task.status
        now = datetime.now(timezone.utc)
        if target is TaskStatus.RUNNING and task.started_at is None:
            task.started_at = now
        if target in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.TIMEOUT,
            TaskStatus.CANCELLED,
        }:
            task.completed_at = now
        task.status = target
        task.error_message = error_message

        self._persist_status(task)
        self._publish(
            "task.status", task, self._status_event_payload(task, previous_status, error_message)
        )
        if target in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.TIMEOUT,
            TaskStatus.CANCELLED,
        }:
            self._publish("task.complete", task, self._completion_event_payload(task))
        return task

    def _persist_status(self, task: Task) -> None:
        """持久化状态变更。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            self.storage.update_task(
                task.task_id,
                status=task.status.value,
                started_at=task.started_at.isoformat() if task.started_at else None,
                completed_at=task.completed_at.isoformat() if task.completed_at else None,
                error_message=task.error_message,
                result_summary=task.result_summary,
                report_path=task.report_path,
            )
        else:
            self.storage.save(task)

    def _status_event_payload(
        self, task: Task, previous_status: TaskStatus, error_message: str | None
    ) -> dict[str, Any]:
        """生成 task.status 事件负载。"""
        return {
            "previousStatus": previous_status.value,
            "status": task.status.value,
            "errorMessage": error_message,
            "task": _task_summary(task),
        }

    def _completion_event_payload(self, task: Task) -> dict[str, Any]:
        """生成 task.complete 事件负载。"""
        return {
            "status": task.status.value,
            "resultSummary": _redact_optional_text(task.result_summary),
            "errorMessage": _redact_optional_text(task.error_message),
            "reportPath": _path_name(task.report_path),
            "task": _task_summary(task),
        }

    def restart_task(self, task: Task | str) -> Task:
        """复制已结束的任务为新 pending 任务（重试）。"""
        resolved = self._resolve_task(task)
        if resolved.status not in (
            TaskStatus.FAILED,
            TaskStatus.TIMEOUT,
            TaskStatus.CANCELLED,
        ):
            raise TaskError(
                f"只有失败/超时/取消的任务可以重试，当前状态：{resolved.status.value}。"
            )

        name = resolved.name
        if name:
            name = f"{name} - 重试"

        new_task = Task(
            goal=resolved.goal,
            name=name,
            start_url=resolved.start_url,
            task_type=resolved.task_type,
            project_id=resolved.project_id,
            max_steps=resolved.max_steps,
            timeout_seconds=resolved.timeout_seconds,
            capture_screenshots=resolved.capture_screenshots,
            parameters=dict(resolved.parameters),
        )
        self.storage.save(new_task)
        self._publish("task.created", new_task, {"task": _task_summary(new_task)})
        audit(
            "task.restart",
            task_id=new_task.task_id,
            sourceTaskId=resolved.task_id,
            task=_task_summary(new_task),
        )
        return new_task

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
        resolved = self._resolve_task(task)
        token = self.get_cancellation_token(resolved.task_id)
        token.cancel()
        audit(
            "task.cancel",
            task_id=resolved.task_id,
            status="cancelled",
            previousStatus=resolved.status.value,
        )
        return self.update_status(resolved, TaskStatus.CANCELLED)

    def pause_task(self, task: Task | str) -> Task:
        """将运行中的任务标记为暂停。"""
        resolved = self._resolve_task(task)
        token = self.get_cancellation_token(resolved.task_id)
        token.pause()
        return self.update_status(resolved, TaskStatus.PAUSED)

    def resume_task(self, task: Task | str) -> Task:
        """将暂停的任务恢复为运行中。"""
        resolved = self._resolve_task(task)
        token = self.get_cancellation_token(resolved.task_id)
        token.resume()
        return self.update_status(resolved, TaskStatus.RUNNING)


def _task_summary(task: Task) -> dict[str, Any]:
    """生成轻量任务摘要，避免每个事件重复携带完整日志。"""
    return {
        "taskId": task.task_id,
        "projectId": task.project_id,
        "name": task.name,
        "goal": redact_sensitive_text(task.goal),
        "startUrl": redact_href(task.start_url) if task.start_url else None,
        "taskType": task.task_type.value,
        "status": task.status.value,
        "currentStep": task.current_step,
        "findingCount": task.finding_count,
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
