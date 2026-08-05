"""任务存储：文件系统（兼容旧版）和 SQLite（默认，委托 repository 模块）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from argus_py.analysis.enums import AnalysisRunStatus
from argus_py.core.exceptions import TaskNotFoundError
from argus_py.core.paths import DATA_DIR, TEMP_DIR
from argus_py.correlation.models import (
    BlackboxRun,
    CaptureQuality,
    CorrelationAttempt,
    CorrelationAttemptDiagnostic,
    CorrelationAttemptReason,
    CorrelationRun,
    CorrelationSummary,
    EndpointEvidence,
    EndpointEvidenceCandidate,
    EndpointEvidenceFlow,
    FindingEvidence,
    FindingEvidenceLink,
    HttpRequestEvidence,
)
from argus_py.task.models import Finding, Task, TaskLog
from argus_py.task.repositories.analysis_repo import AnalysisRunRepository
from argus_py.task.repositories.correlation_repo import CorrelationRepository
from argus_py.task.repositories.event_repo import EventRepository
from argus_py.task.repositories.finding_repo import FindingRepository
from argus_py.task.repositories.log_repo import LogRepository
from argus_py.task.repositories.task_repo import TaskRepository
from argus_py.utils.jsonx import read_json, to_jsonable, write_json


class TaskFileStorage:
    """基于文件系统的任务存储，供 MVP 阶段替代数据库。"""

    def __init__(self, base_dir: str | Path = TEMP_DIR / "tasks") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def task_path(self, task_id: str) -> Path:
        """返回任务 JSON 路径。"""
        return self.base_dir / f"{task_id}.json"

    def exists(self, task_id: str) -> bool:
        """判断任务快照是否存在。"""
        return self.task_path(task_id).exists()

    def save(self, task: Task) -> Path:
        """保存任务快照。"""
        return write_json(self.task_path(task.task_id), to_jsonable(task))

    def load_raw(self, task_id: str) -> dict:
        """读取任务原始 JSON 数据。"""
        return read_json(self.task_path(task_id))

    def load(self, task_id: str) -> Task:
        """读取并还原任务实体。"""
        return Task.from_dict(self.load_raw(task_id))

    def list_ids(self) -> list[str]:
        """列出已保存任务 ID（按文件名字母序，即大致按创建时间排序）。"""
        return sorted(path.stem for path in self.base_dir.glob("*.json"))

    def list_tasks(self, offset: int = 0, limit: int | None = None) -> list[Task]:
        """列出已保存任务，支持分页以减轻磁盘 I/O。"""
        ids = self.list_ids()
        ids.reverse()
        if offset:
            ids = ids[offset:]
        if limit is not None:
            ids = ids[:limit]
        tasks = [self.load(task_id) for task_id in ids]
        return sorted(tasks, key=lambda item: item.created_at, reverse=True)

    def count_tasks(self) -> int:
        """快速返回任务总数（仅列文件名，不反序列化）。"""
        return len(self.list_ids())

    def delete(self, task_id: str) -> None:
        """删除任务快照。"""
        path = self.task_path(task_id)
        if not path.exists():
            raise TaskNotFoundError(f"Task not found: {task_id}")
        path.unlink()


class TaskSQLiteStorage:
    """基于 SQLite 的任务存储（facade，委托 repository 模块）。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        from argus_py.infra.db import get_db_pool, init_database

        self.db_path = Path(db_path) if db_path else DATA_DIR / "argus.db"
        init_database(self.db_path)
        pool = get_db_pool(self.db_path)
        self._tasks = TaskRepository(pool)
        self._logs = LogRepository(pool)
        self._findings = FindingRepository(pool)
        self._events = EventRepository(pool)
        self._analysis = AnalysisRunRepository(pool)
        self._correlation = CorrelationRepository(pool)

    # ── 任务 CRUD ───────────────────────────────────────────

    def exists(self, task_id: str) -> bool:
        return self._tasks.exists(task_id)

    def load_task_header(self, task_id: str) -> dict | None:
        return self._tasks.load_task_header(task_id)

    def get_report_path(self, task_id: str) -> str | None:
        return self._tasks.get_report_path(task_id)

    def get_task_status(self, task_id: str) -> str | None:
        return self._tasks.get_task_status(task_id)

    def update_external_job_checkpoint(
        self,
        task_id: str,
        external_job_status: str,
        external_job_last_polled_at: str,
        *,
        expected_status: str | None = None,
    ) -> int:
        """窄更新：只写 external_job 字段，不覆盖 status。"""
        return self._tasks.update_external_job_checkpoint(
            task_id,
            external_job_status,
            external_job_last_polled_at,
            expected_status=expected_status,
        )

    def save(self, task: Task) -> Task:
        return self._tasks.save(task)

    def update_task(self, task_id: str, **fields: Any) -> None:
        self._tasks.update_task(task_id, **fields)

    def load(self, task_id: str) -> Task:
        return self._tasks.load(task_id)

    def delete(self, task_id: str) -> None:
        self._tasks.delete(task_id)

    def list_tasks(
        self,
        offset: int = 0,
        limit: int | None = None,
        status: str | None = None,
        project_id: str | None = None,
    ) -> list[Task]:
        return self._tasks.list_tasks(offset, limit, status, project_id)

    def count_tasks(
        self,
        status: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> int:
        return self._tasks.count_tasks(status, project_id, q)

    def list_task_summaries(
        self,
        offset: int = 0,
        limit: int | None = None,
        status: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> tuple[list[Task], int]:
        return self._tasks.list_task_summaries(offset, limit, status, project_id, q)

    # ── 步骤日志 ─────────────────────────────────────────────

    def append_log(self, task_id: str, log: TaskLog) -> None:
        self._logs.append(task_id, log)

    def append_log_batch(self, entries: list[tuple[str, TaskLog]]) -> None:
        """批量追加步骤日志（单事务 executemany）。"""
        self._logs.append_batch(entries)

    # ── 发现项 ───────────────────────────────────────────────

    def append_finding(self, task_id: str, finding: Finding) -> None:
        self._findings.append(task_id, finding)

    def delete_findings_by_analysis_id(self, analysis_id: str) -> None:
        """删除指定分析执行的所有发现项（幂等清理）。"""
        self._findings.delete_by_analysis_id(analysis_id)

    def count_findings(self) -> int:
        """返回 findings 表总记录数（供仪表盘统计）。"""
        return self._findings.count_all()

    def get_analysis_findings(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[Finding], str | None, int | None, bool]:
        """按 analysis_id 分页查询发现项。"""
        return self._findings.list_by_analysis_id(analysis_id, cursor=cursor, limit=limit)

    # ── 时间线事件 ────────────────────────────────────────────

    def append_event(self, event: Any) -> None:
        self._events.append(event)

    def append_event_batch(self, events: list[Any]) -> None:
        """批量追加时间线事件（单事务 executemany）。"""
        self._events.append_batch(events)

    def load_events(self, task_id: str) -> list[Any]:
        return self._events.load(task_id)

    def delete_events(self, task_id: str) -> None:
        self._events.delete(task_id)

    # ── 分析执行 ────────────────────────────────────────────

    def create_analysis_run(self, run: Any) -> Any:
        return self._analysis.create(run)

    def get_analysis_run(self, analysis_id: str) -> Any:
        return self._analysis.get(analysis_id)

    def list_analysis_runs(
        self, task_id: str, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[Any], int]:
        return self._analysis.list_by_task(task_id, offset=offset, limit=limit)

    def get_latest_analysis_run(self, task_id: str) -> Any:
        return self._analysis.get_latest(task_id)

    def get_latest_succeeded_analysis_by_project(
        self, project_id: str, *, source_snapshot_id: str | None = None
    ) -> Any:
        """查找同一项目下最新成功的分析执行。

        source_snapshot_id 非空时仅返回 resolved_commit_sha 一致的分析。
        """
        return self._analysis.get_latest_succeeded_by_project(
            project_id, source_snapshot_id=source_snapshot_id
        )

    def update_analysis_run_status(self, analysis_id: str, run_status: str, **kw: Any) -> None:
        self._analysis.update_status(analysis_id, run_status, **kw)

    def save_analysis_raw_result(self, analysis_id: str, raw_json: str, digest: str) -> None:
        self._analysis.save_raw_result(analysis_id, raw_json, digest)

    def mark_analysis_failed(
        self, analysis_id: str, failure_code: str, failure_message: str
    ) -> None:
        self._analysis.mark_failed(analysis_id, failure_code, failure_message)

    def mark_analysis_terminal(
        self,
        analysis_id: str,
        run_status: AnalysisRunStatus,
        failure_code: str,
        failure_message: str,
    ) -> None:
        """将 analysis_runs 置为取消/超时等非失败终态。"""
        self._analysis.mark_terminal(
            analysis_id,
            run_status,
            failure_code,
            failure_message,
        )

    def complete_analysis_projection(
        self,
        analysis_id: str,
        *,
        completeness: str,
        quality_issues_json: str,
        result_digest: str,
        projection_data: dict[str, Any],
    ) -> None:
        self._analysis.complete_projection(
            analysis_id,
            completeness=completeness,
            quality_issues_json=quality_issues_json,
            result_digest=result_digest,
            projection_data=projection_data,
        )

    def list_analysis_endpoints(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._analysis.list_endpoints(analysis_id, cursor=cursor, limit=limit)

    def list_analysis_call_nodes(
        self,
        analysis_id: str,
        *,
        class_name: str | None = None,
        method_name: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._analysis.list_call_nodes(
            analysis_id,
            class_name=class_name,
            method_name=method_name,
            cursor=cursor,
            limit=limit,
        )

    def list_analysis_call_edges(
        self,
        analysis_id: str,
        *,
        entry_node_id: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._analysis.list_call_edges(
            analysis_id,
            entry_node_id=entry_node_id,
            cursor=cursor,
            limit=limit,
        )

    def list_analysis_execution_flows(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._analysis.list_execution_flows(analysis_id, cursor=cursor, limit=limit)

    def get_analysis_flow_steps(self, flow_id: str) -> list[dict[str, Any]]:
        return self._analysis.get_flow_steps(flow_id)

    def list_all_analysis_flow_steps(self, analysis_id: str) -> list[dict[str, Any]]:
        """一次查询获取分析的所有 flow steps，避免 N+1 查询。"""
        return self._analysis.list_all_flow_steps_by_analysis(analysis_id)

    def get_analysis_diagnostics(self, analysis_id: str) -> dict[str, Any] | None:
        return self._analysis.get_diagnostics(analysis_id)

    def get_analysis_counts(self, analysis_id: str) -> dict[str, int]:
        return self._analysis.get_counts(analysis_id)

    def list_analysis_clusters(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[Any], str | None, int | None, bool]:
        return self._analysis.list_clusters(analysis_id, cursor=cursor, limit=limit)

    def get_analysis_finding_severity_counts(self, analysis_id: str) -> dict[str, int]:
        return self._analysis.get_finding_severity_counts(analysis_id)

    # ── 关联（BlackboxRun / CorrelationRun / Evidence）───

    # BlackboxRun
    def create_blackbox_run(self, run: BlackboxRun) -> BlackboxRun:
        return self._correlation.create_blackbox_run(run)

    def get_blackbox_run(self, blackbox_run_id: str) -> BlackboxRun | None:
        return self._correlation.get_blackbox_run(blackbox_run_id)

    def update_blackbox_run_status(
        self,
        blackbox_run_id: str,
        status: str,
        completed_at: str | None = None,
    ) -> None:
        self._correlation.update_blackbox_run_status(blackbox_run_id, status, completed_at)

    # CorrelationRun
    def create_correlation_run(self, run: CorrelationRun) -> CorrelationRun:
        return self._correlation.create_correlation_run(run)

    def get_correlation_run(self, correlation_run_id: str) -> CorrelationRun | None:
        return self._correlation.get_correlation_run(correlation_run_id)

    def get_correlation_run_by_blackbox(self, blackbox_run_id: str) -> CorrelationRun | None:
        return self._correlation.get_correlation_run_by_blackbox(blackbox_run_id)

    def find_waiting_correlations(
        self,
        snapshot_id: str,
        *,
        project_id: str | None = None,
    ) -> list[CorrelationRun]:
        return self._correlation.find_waiting_analysis(snapshot_id, project_id=project_id)

    def bind_correlation_analysis(
        self,
        correlation_run_id: str,
        analysis_id: str,
        snapshot_id: str,
        projection_version: int,
        alignment: str,
        *,
        source_mismatch_overridden: bool = False,
        source_mismatch_override_by: str | None = None,
        source_mismatch_override_at: str | None = None,
        source_mismatch_override_reason: str | None = None,
    ) -> None:
        self._correlation.bind_analysis(
            correlation_run_id,
            analysis_id,
            snapshot_id,
            projection_version,
            alignment,
            source_mismatch_overridden=source_mismatch_overridden,
            source_mismatch_override_by=source_mismatch_override_by,
            source_mismatch_override_at=source_mismatch_override_at,
            source_mismatch_override_reason=source_mismatch_override_reason,
        )

    def claim_and_create_attempt(
        self,
        correlation_run_id: str,
        worker_id: str,
    ) -> CorrelationAttempt | None:
        return self._correlation.claim_and_create_attempt(correlation_run_id, worker_id)

    def set_correlation_status(self, correlation_run_id: str, status: str) -> None:
        from argus_py.correlation.enums import CorrelationRunStatus

        self._correlation.set_status(correlation_run_id, CorrelationRunStatus(status))

    def complete_and_activate_attempt(
        self,
        attempt_id: str,
        status: str,
        completeness: str = "COMPLETE",
    ) -> None:
        from argus_py.correlation.enums import AttemptStatus, EvidenceCompleteness

        self._correlation.complete_and_activate_attempt(
            attempt_id,
            AttemptStatus(status),
            EvidenceCompleteness(completeness),
        )

    # HttpRequestEvidence
    def insert_http_request_batch(self, items: list[HttpRequestEvidence]) -> None:
        self._correlation.insert_request_batch(items)

    def list_http_requests(
        self,
        bb_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[HttpRequestEvidence], int]:
        return self._correlation.list_requests_by_blackbox_run(bb_id, offset=offset, limit=limit)

    def list_eligible_requests(self, bb_id: str) -> list[HttpRequestEvidence]:
        return self._correlation.list_eligible_requests(bb_id)

    def list_unmatched_requests(
        self,
        cr_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[HttpRequestEvidence], int]:
        return self._correlation.list_unmatched_requests(cr_id, offset=offset, limit=limit)

    def list_uncovered_endpoints(
        self,
        cr_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        return self._correlation.list_uncovered_endpoints(cr_id, offset=offset, limit=limit)

    # EndpointEvidence + 关系表
    def insert_endpoint_evidence_batch(self, items: list[EndpointEvidence]) -> None:
        self._correlation.insert_evidence_batch(items)

    def insert_candidates_batch(self, items: list[EndpointEvidenceCandidate]) -> None:
        self._correlation.insert_candidates_batch(items)

    def insert_flows_batch(self, items: list[EndpointEvidenceFlow]) -> None:
        self._correlation.insert_flows_batch(items)

    def list_endpoint_evidence(
        self,
        attempt_id: str,
        *,
        resolution_status: str | None = None,
        match_strategy: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        return self._correlation.list_evidence_by_attempt(
            attempt_id,
            resolution_status=resolution_status,
            match_strategy=match_strategy,
            offset=offset,
            limit=limit,
        )

    def get_correlation_summary(self, correlation_run_id: str) -> CorrelationSummary:
        return self._correlation.get_summary(correlation_run_id)

    # FindingEvidence
    def insert_finding_evidence_batch(self, items: list[FindingEvidence]) -> None:
        self._correlation.insert_finding_evidence_batch(items)

    def insert_finding_links_batch(self, items: list[FindingEvidenceLink]) -> None:
        self._correlation.insert_finding_links_batch(items)

    def list_finding_evidence(
        self,
        cr_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        return self._correlation.list_finding_evidence(cr_id, offset=offset, limit=limit)

    # 批量查询辅助
    def batch_get_candidates(self, evidence_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        return self._correlation.batch_get_candidates(evidence_ids)

    def batch_get_flows(self, evidence_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        return self._correlation.batch_get_flows(evidence_ids)

    def batch_get_endpoint_details(self, endpoint_ids: list[str]) -> dict[str, dict[str, Any]]:
        return self._correlation.batch_get_endpoint_details(endpoint_ids)

    def batch_get_finding_details(self, finding_ids: list[str]) -> dict[str, dict[str, Any]]:
        return self._correlation.batch_get_finding_details(finding_ids)

    # Attempt 明细
    def list_confirmed_touched_endpoints(self, attempt_id: str) -> list[dict[str, Any]]:
        return self._correlation.list_confirmed_touched_endpoints(attempt_id)

    def insert_attempt_reasons_batch(self, items: list[CorrelationAttemptReason]) -> None:
        self._correlation.insert_attempt_reasons_batch(items)

    def insert_attempt_diagnostics_batch(self, items: list[CorrelationAttemptDiagnostic]) -> None:
        self._correlation.insert_attempt_diagnostics_batch(items)

    # CaptureQuality
    def upsert_capture_quality(self, quality: CaptureQuality) -> None:
        self._correlation.upsert_capture_quality(quality)

    def get_capture_quality(self, blackbox_run_id: str) -> dict[str, Any] | None:
        with self._correlation._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM http_capture_quality WHERE blackbox_run_id = ?",
                (blackbox_run_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    # 崩溃恢复
    def recover_stale_attempts(self) -> list[CorrelationAttempt]:
        return self._correlation.recover_stale_attempts()
