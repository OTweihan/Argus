"""任务生命周期管理。"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

from argus_py.analysis.enums import AnalysisRunStatus
from argus_py.core.cancellation import CancellationToken
from argus_py.core.constants import DEFAULT_MAX_STEPS, DEFAULT_TASK_TIMEOUT_S, utc_now
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError, TaskNotFoundError
from argus_py.observability import audit
from argus_py.redaction import redact_href, redact_sensitive_text
from argus_py.task._base import TaskEventPublisher, _StorageEventBase
from argus_py.task.models import Task, normalize_task_name
from argus_py.task.policies import can_delete, can_edit, can_retry
from argus_py.task.status import assert_transition
from argus_py.task.storage import TaskSQLiteStorage

__all__ = ["TaskEventPublisher", "TaskLifecycleService"]


class _UnsetType:
    """区分"字段未提供"与"显式传 None"的哨兵类型。"""

    __slots__ = ()


# 更新接口中"未提供 name"的标记：调用方不传时保持原名，而不是误清空。
_UNSET: Final = _UnsetType()

# 任务终态集合：终态流转必须走「单次全量落盘」路径（complete/fail/timeout/cancel_task），
# 避免 SQLite UPDATE 整行重写导致大 result_json 双写。
_TERMINAL_TASK_STATUSES: Final[frozenset[TaskStatus]] = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED}
)


class TaskLifecycleService(_StorageEventBase):
    """管理任务创建、删除、状态流转和取消令牌。"""

    def __init__(
        self,
        storage: TaskSQLiteStorage,
        event_publisher: TaskEventPublisher | None,
    ) -> None:
        super().__init__(storage, event_publisher)
        self._cancellation_tokens: dict[str, CancellationToken] = {}
        # 注册表锁：事件循环线程（application 层 cancel/pause/resume、runner
        # 轮询读取）与 IO 线程（lifecycle 同名方法经 run_in_thread 调用）都会
        # 访问本注册表。信号布尔位幂等且 GIL 下读写原子；锁只保护懒创建的
        # check-then-act 窗口，避免双创建导致一方的取消/暂停信号写入孤儿
        # token 而丢失。
        self._token_lock = threading.Lock()

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
        name: str | None | _UnsetType = _UNSET,
        start_url: str | None,
        task_type: TaskType,
        project_id: str | None,
        max_steps: int,
        timeout_seconds: int,
        capture_screenshots: bool,
        parameters: dict[str, Any],
        whitebox_config_json: str | None = None,
    ) -> Task:
        """更新待执行任务的基础信息。

        ``name`` 三态语义：
          - 未提供（保持 ``_UNSET``）→ 保持原名称
          - 显式 ``None`` / ``""`` / 纯空白 → 归一化为 task_id 后 8 位
          - 正常值 → 去除首尾空白后使用
        """
        resolved = self._resolve_task(task)
        if not can_edit(resolved.status):
            raise TaskError(f"只有 pending 任务可以编辑，当前状态：{resolved.status.value}。")

        resolved.goal = goal
        if not isinstance(name, _UnsetType):
            resolved.name = normalize_task_name(name, resolved.task_id)
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
        """获取任务的取消/暂停信号量，懒创建（线程协议见构造函数注释）。"""
        with self._token_lock:
            if task_id not in self._cancellation_tokens:
                self._cancellation_tokens[task_id] = CancellationToken()
            return self._cancellation_tokens[task_id]

    def remove_cancellation_token(self, task_id: str) -> None:
        """移除任务的取消/暂停信号量。"""
        with self._token_lock:
            self._cancellation_tokens.pop(task_id, None)

    def update_status(
        self, task: Task, target: TaskStatus, error_message: str | None = None
    ) -> Task:
        """更新任务状态（窄更新：仅状态与租约相关字段落盘）。

        终态流转请使用 complete/fail/timeout/cancel_task——它们把状态字段并入
        全量保存，避免大 result_json 双写。
        """
        previous_status = self._apply_transition(task, target, error_message)
        self._persist_status(task)
        self._publish_task_status_events(task, target, previous_status, error_message)
        return task

    def _apply_transition(
        self, task: Task, target: TaskStatus, error_message: str | None = None
    ) -> TaskStatus:
        """内存态推进状态转移（不落盘），返回 previous_status。

        RUNNING 时补 started_at；终态时设置 completed_at 并移除取消令牌。
        落盘方式由调用方决定：非终态走窄更新（_persist_status），终态走
        全量保存（_save_and_publish_terminal）。
        """
        assert_transition(task.status, target)
        previous_status = task.status
        now = datetime.now(timezone.utc)
        if target is TaskStatus.RUNNING and task.started_at is None:
            task.started_at = now
        if target in _TERMINAL_TASK_STATUSES:
            task.completed_at = now
            self.remove_cancellation_token(task.task_id)
        task.status = target
        task.error_message = error_message
        return previous_status

    def _publish_task_status_events(
        self,
        task: Task,
        target: TaskStatus,
        previous_status: TaskStatus,
        error_message: str | None,
    ) -> None:
        """发布 task.status 事件；终态追加 task.complete。"""
        self._publish(
            "task.status", task, self._status_event_payload(task, previous_status, error_message)
        )
        if target in _TERMINAL_TASK_STATUSES:
            self._publish("task.complete", task, self._completion_event_payload(task))

    def _save_and_publish_terminal(self, task: Task, previous_status: TaskStatus) -> None:
        """终态落盘：状态与 result_json 合并为单次全量写入，随后发布事件。

        此前实现是「全量 save + 窄 UPDATE」两次落盘——SQLite 的 UPDATE 会
        重写整行，等于把可达数十 MB 的 result_json 写两遍（WAL 与 fsync 翻倍）。
        """
        self.storage.save(task)
        self._publish(
            "task.status",
            task,
            self._status_event_payload(task, previous_status, task.error_message),
        )
        self._publish("task.complete", task, self._completion_event_payload(task))

    def _persist_status(self, task: Task) -> None:
        """持久化状态变更（仅更新状态与租约相关字段，不做全量覆盖）。"""
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
        """复制已结束的任务为新 pending 任务（重试）。

        新任务继承**重试链根任务**的 name（同一重试链基础名一致，不再追加
        「-重试」后缀），并通过 ``retry_parent_task_id`` 记录直接前驱，保证
        重试链严格线性。调用方（应用层）需确保当前任务没有直接重试子任务。
        """
        resolved = self._resolve_task(task)
        if not can_retry(resolved.status):
            raise TaskError(
                f"只有失败/超时/取消的任务可以重试，当前状态：{resolved.status.value}。"
            )

        new_task = Task(
            goal=resolved.goal,
            name=self._root_task_name(resolved),
            start_url=resolved.start_url,
            task_type=resolved.task_type,
            project_id=resolved.project_id,
            max_steps=resolved.max_steps,
            timeout_seconds=resolved.timeout_seconds,
            capture_screenshots=resolved.capture_screenshots,
            parameters=dict(resolved.parameters),
            whitebox_config_json=resolved.whitebox_config_json,
            execution_attempt=resolved.execution_attempt + 1,
            retry_parent_task_id=resolved.task_id,
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

    def _root_task_name(self, task: Task) -> str:
        """沿重试链回溯到根任务，返回根任务的基础名（链上名称统一）。

        若链上父任务已被删除（如删除 pending 重试子任务导致链断裂），退化为
        以当前任务名为基础名；`Task.__post_init__` 保证 name 恒非空。
        """
        current = task
        while current.retry_parent_task_id:
            try:
                current = self.storage.load(current.retry_parent_task_id)
            except TaskNotFoundError:
                break
        return normalize_task_name(current.name, current.task_id)

    def has_retry_child(self, task_id: str) -> bool:
        """当前任务是否已存在直接重试子任务。"""
        return self.storage.has_retry_child(task_id)

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

        状态变更与 handler 写入的 findings/result_json 合并为**同一次**全量
        落盘，避免整行双写（语义见 _save_and_publish_terminal）。
        """
        resolved = self._resolve_task(task)
        if result_summary is not None:
            resolved.result_summary = result_summary
        if report_path is not None:
            resolved.report_path = report_path
        previous_status = self._apply_transition(resolved, TaskStatus.COMPLETED)
        self._save_and_publish_terminal(resolved, previous_status)
        return resolved

    def fail_task(self, task: Task | str, error_message: str) -> Task:
        """将任务标记为失败（单次全量落盘，语义同 complete_task）。"""
        resolved = self._resolve_task(task)
        previous_status = self._apply_transition(resolved, TaskStatus.FAILED, error_message)
        self._save_and_publish_terminal(resolved, previous_status)
        return resolved

    def timeout_task(self, task: Task | str, error_message: str = "任务执行超时。") -> Task:
        """将任务标记为超时（单次全量落盘，语义同 complete_task）。"""
        resolved = self._resolve_task(task)
        previous_status = self._apply_transition(resolved, TaskStatus.TIMEOUT, error_message)
        self._save_and_publish_terminal(resolved, previous_status)
        return resolved

    def cancel_task(self, task: Task | str) -> Task:
        """将任务标记为取消（单次全量落盘，语义同 complete_task）。"""
        resolved = self._resolve_task(task)
        token = self.get_cancellation_token(resolved.task_id)
        token.cancel()
        audit(
            "task.cancel",
            task_id=resolved.task_id,
            status="cancelled",
            previous_status=resolved.status.value,
        )
        previous_status = self._apply_transition(resolved, TaskStatus.CANCELLED)
        self._save_and_publish_terminal(resolved, previous_status)
        return resolved

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
        """创建分析执行记录。"""
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

    def start_analysis_run(self, analysis_id: str) -> None:
        """分析执行：QUEUED → RUNNING。

        SUBMITTING 状态不存在可观察窗口（紧随其后的 RUNNING 立即写入），
        直接落 RUNNING 减少一次不必要的事务更新。
        """
        self.storage.update_analysis_run_status(
            analysis_id, "RUNNING", started_at=utc_now().isoformat()
        )

    def reset_analysis_run(self, analysis_id: str) -> None:
        """重新接管时复位非终态 analysis_run 供再次执行（O-04 启动恢复）。

        复用同一 analysis_id（避免 UNIQUE 冲突重复插入），清空上次运行的
        失败/完成痕迹，回到 QUEUED 由新一次执行驱动。
        """
        self.storage.update_analysis_run_status(
            analysis_id,
            "QUEUED",
            completeness_status="NOT_EVALUATED",
            failure_code=None,
            failure_message=None,
            stop_reason=None,
            started_at=None,
            completed_at=None,
            projection_completed_at=None,
        )

    def save_analysis_raw_result(self, analysis_id: str, raw_json: str, digest: str) -> None:
        """事务 1：独立保存 Java 原始响应（审计留存）。"""
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
        self.storage.mark_analysis_failed(analysis_id, failure_code, failure_message)

    def mark_analysis_terminal(
        self,
        analysis_id: str,
        run_status: AnalysisRunStatus,
        failure_code: str,
        failure_message: str,
    ) -> None:
        """将 analysis_runs 置为取消/超时等非失败终态（STOPPED_WAITING / CANCELLED / TIMED_OUT）。"""
        self.storage.mark_analysis_terminal(analysis_id, run_status, failure_code, failure_message)

    def save_task_findings(self, task: Task) -> None:
        """持久化任务的 findings 列表（含 snippet / analysis_id）。

        先删除同 analysis_id 的已有记录（幂等），再写入新 findings，
        避免同一任务重复执行时 findings 表累积历史数据。"""
        # 从第一条 finding 提取 analysis_id（同批次 findings 的 analysis_id 一致）
        if task.findings:
            first_aid = task.findings[0].analysis_id
            if first_aid:
                self.storage.delete_findings_by_analysis_id(first_aid)
        self.storage.insert_findings_batch(task.task_id, task.findings)


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
        "executionAttempt": task.execution_attempt,
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
