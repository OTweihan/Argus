"""任务生命周期管理。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from argus_py.core.cancellation import CancellationToken
from argus_py.core.constants import DEFAULT_MAX_STEPS, DEFAULT_TASK_TIMEOUT_S
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.observability import audit
from argus_py.redaction import redact_href, redact_sensitive_text
from argus_py.task._base import TaskEventPublisher, _StorageEventBase
from argus_py.task.models import Task
from argus_py.task.policies import can_delete, can_edit, can_retry
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
        max_steps: int = DEFAULT_MAX_STEPS,
        timeout_seconds: int = DEFAULT_TASK_TIMEOUT_S,
        capture_screenshots: bool = True,
        parameters: dict[str, Any] | None = None,
        whitebox_config_json: str | None = None,
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
            whitebox_config_json=whitebox_config_json,
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
        whitebox_config_json: str | None = None,
    ) -> Task:
        """更新待执行任务的基础信息。"""
        resolved = self._resolve_task(task)
        if not can_edit(resolved.status):
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
        if whitebox_config_json is not None:
            resolved.whitebox_config_json = whitebox_config_json
        self.storage.save(resolved)
        self._publish("task.updated", resolved, {"task": _task_summary(resolved)})
        audit("task.update", task_id=resolved.task_id, task=_task_summary(resolved))
        return resolved

    def delete_pending_task(self, task: Task | str) -> None:
        """删除未启动的 pending 任务。"""
        resolved = self._resolve_task(task)
        if not can_delete(resolved.status):
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
            self.remove_cancellation_token(task.task_id)
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
        """持久化状态变更（仅更新状态与租约相关字段，不做全量覆盖）。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            self.storage.update_task(
                task.task_id,
                status=task.status.value,
                started_at=task.started_at.isoformat() if task.started_at else None,
                completed_at=task.completed_at.isoformat() if task.completed_at else None,
                error_message=task.error_message,
                result_summary=task.result_summary,
                report_path=task.report_path,
                worker_id=task.worker_id,
                worker_lease_expires_at=task.worker_lease_expires_at,
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
        if not can_retry(resolved.status):
            raise TaskError(
                f"只有失败/超时/取消的任务可以重试，当前状态：{resolved.status.value}。"
            )

        name = resolved.name
        if name:
            name = f"{name}-重试"

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
            whitebox_config_json=resolved.whitebox_config_json,
            execution_attempt=resolved.execution_attempt + 1,
        )
        self.storage.save(new_task)
        self._publish("task.created", new_task, {"task": _task_summary(new_task)})
        audit(
            "task.restart",
            task_id=new_task.task_id,
            source_task_id=resolved.task_id,
            task=_task_summary(new_task),
        )
        return new_task

    def start_task(self, task: Task | str, worker_id: str | None = None) -> Task:
        """将任务标记为运行中，并写入 worker 租约。"""
        resolved = self._resolve_task(task)
        if worker_id:
            resolved.worker_id = worker_id
            resolved.worker_lease_expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=resolved.timeout_seconds + 120)
            ).isoformat()
        return self.update_status(resolved, TaskStatus.RUNNING)

    def complete_task(
        self,
        task: Task | str,
        result_summary: str | None = None,
        report_path: str | None = None,
    ) -> Task:
        """将任务标记为完成。

        先全量持久化 task（确保 findings/result_json 等 handler 写入的
        字段落盘），再走局部状态更新。避免 _persist_status 只写 6 个字段
        导致白盒分析结果丢失。
        """
        resolved = self._resolve_task(task)
        if result_summary is not None:
            resolved.result_summary = result_summary
        if report_path is not None:
            resolved.report_path = report_path
        self.storage.save(resolved)
        return self.update_status(resolved, TaskStatus.COMPLETED)

    def fail_task(self, task: Task | str, error_message: str) -> Task:
        """将任务标记为失败。

        先全量持久化再局部更新状态，避免 handler 写入的额外字段丢失。
        """
        resolved = self._resolve_task(task)
        self.storage.save(resolved)
        return self.update_status(resolved, TaskStatus.FAILED, error_message)

    def timeout_task(self, task: Task | str, error_message: str = "任务执行超时。") -> Task:
        """将任务标记为超时。

        先全量持久化再局部更新状态，避免 handler 写入的额外字段丢失。
        """
        resolved = self._resolve_task(task)
        self.storage.save(resolved)
        return self.update_status(resolved, TaskStatus.TIMEOUT, error_message)

    def cancel_task(self, task: Task | str) -> Task:
        """将任务标记为取消。

        先全量持久化再局部更新状态，避免 handler 写入的额外字段丢失。
        """
        resolved = self._resolve_task(task)
        token = self.get_cancellation_token(resolved.task_id)
        token.cancel()
        audit(
            "task.cancel",
            task_id=resolved.task_id,
            status="cancelled",
            previous_status=resolved.status.value,
        )
        self.storage.save(resolved)
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

    # ── 分析执行（阶段二：白盒结果）──────────────────────────────

    def create_analysis_run(
        self,
        analysis_id: str,
        task_id: str,
        source_snapshot_id: str,
        *,
        resolved_commit_sha: str | None = None,
        external_job_id: str | None = None,
        result_schema_version: int = 1,
        config_json: str | None = None,
    ) -> Any:
        """创建分析执行记录（SQLite 后端；FileStorage 返回 None）。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            from argus_py.analysis.models import AnalysisRun
            from argus_py.core.constants import utc_now as _utc_now

            now = _utc_now().isoformat()
            run = AnalysisRun(
                analysis_id=analysis_id,
                task_id=task_id,
                source_snapshot_id=source_snapshot_id,
                resolved_commit_sha=resolved_commit_sha,
                run_status="QUEUED",
                completeness_status="NOT_EVALUATED",
                external_job_id=external_job_id,
                result_schema_version=result_schema_version,
                config_json=config_json or "{}",
                created_at=now,
                updated_at=now,
            )
            self.storage.create_analysis_run(run)
            return run
        return None

    def start_analysis_run(self, analysis_id: str) -> None:
        """分析执行：QUEUED → SUBMITTING → RUNNING。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            self.storage.update_analysis_run_status(analysis_id, "SUBMITTING")
            self.storage.update_analysis_run_status(analysis_id, "RUNNING")

    def save_analysis_raw_result(self, analysis_id: str, raw_json: str, digest: str) -> None:
        """事务 1：独立保存 Java 原始响应（审计留存）。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            self.storage.save_analysis_raw_result(analysis_id, raw_json, digest)

    def complete_analysis_projection(
        self,
        analysis_id: str,
        *,
        completeness: str,
        quality_issues_json: str,
        result_digest: str,
        projection_data: dict[str, Any],
    ) -> None:
        """事务 2：投影写入 + 标记 SUCCEEDED，同一事务。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            self.storage.complete_analysis_projection(
                analysis_id,
                completeness=completeness,
                quality_issues_json=quality_issues_json,
                result_digest=result_digest,
                projection_data=projection_data,
            )

    def mark_analysis_failed(
        self, analysis_id: str, failure_code: str, failure_message: str
    ) -> None:
        """事务 3：投影失败标记。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            self.storage.mark_analysis_failed(analysis_id, failure_code, failure_message)

    def save_task_findings(self, task: Task) -> None:
        """持久化任务的 findings 列表（含 snippet / analysis_id）。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            for finding in task.findings:
                self.storage.append_finding(task.task_id, finding)


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
