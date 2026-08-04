"""黑白盒关联 Repository — blackbox_runs, correlation_runs, attempts, evidence 等表读写。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from argus_py.correlation.enums import (
    AttemptStatus,
    BlackboxRunStatus,
    CorrelationEligibility,
    CorrelationRunStatus,
    EvidenceCompleteness,
    RequestOutcome,
    RequestOwner,
    SourceAlignmentStatus,
)
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
from argus_py.infra.db import DbPool


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex[:12]}"


_LEASE_DURATION_SECONDS = 300


def _lease_expiry() -> str:
    import datetime as _dt

    return (
        _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=_LEASE_DURATION_SECONDS)
    ).isoformat()


# ── BlackboxRun 行映射 ─────────────────────────────────────


def _blackbox_run_to_row(run: BlackboxRun) -> tuple:
    return (
        run.blackbox_run_id,
        run.task_id,
        run.attempt,
        run.status.value,
        run.started_at,
        run.completed_at,
    )


def _row_to_blackbox_run(row: dict[str, Any]) -> BlackboxRun:
    return BlackboxRun(
        blackbox_run_id=row["blackbox_run_id"],
        task_id=row["task_id"],
        attempt=row["attempt"],
        status=BlackboxRunStatus(row["status"]),
        started_at=row["started_at"],
        completed_at=row.get("completed_at"),
    )


# ── CorrelationRun 行映射 ──────────────────────────────────


def _correlation_run_to_row(run: CorrelationRun) -> tuple:
    return (
        run.correlation_run_id,
        run.project_id,
        run.blackbox_run_id,
        run.desired_source_snapshot_id,
        run.desired_analysis_config_digest,
        run.required_analyzer_version,
        int(run.allow_partial_analysis),
        run.analysis_id,
        run.bound_source_snapshot_id,
        run.analysis_projection_version,
        run.correlation_config_digest,
        run.matcher_version,
        run.normalization_version,
        run.supersedes_correlation_run_id,
        run.source_alignment_status.value,
        run.status.value,
        run.active_attempt_id,
        int(run.source_mismatch_overridden),
        run.source_mismatch_override_by,
        run.source_mismatch_override_at,
        run.source_mismatch_override_reason,
        run.started_at,
        run.completed_at,
        run.error_code,
        run.error_message,
        run.created_at or _utc_now_iso(),
    )


def _row_to_correlation_run(row: dict[str, Any]) -> CorrelationRun:
    return CorrelationRun(
        correlation_run_id=row["correlation_run_id"],
        project_id=row["project_id"],
        blackbox_run_id=row["blackbox_run_id"],
        desired_source_snapshot_id=row["desired_source_snapshot_id"],
        desired_analysis_config_digest=row.get("desired_analysis_config_digest", ""),
        required_analyzer_version=row.get("required_analyzer_version", ""),
        allow_partial_analysis=bool(row.get("allow_partial_analysis", 0)),
        analysis_id=row.get("analysis_id"),
        bound_source_snapshot_id=row.get("bound_source_snapshot_id"),
        analysis_projection_version=row.get("analysis_projection_version"),
        correlation_config_digest=row.get("correlation_config_digest", ""),
        matcher_version=row.get("matcher_version", "v1"),
        normalization_version=row.get("normalization_version", "v1"),
        supersedes_correlation_run_id=row.get("supersedes_correlation_run_id"),
        source_alignment_status=SourceAlignmentStatus(
            row.get("source_alignment_status", "UNVERIFIED")
        ),
        status=CorrelationRunStatus(row.get("status", "WAITING_ANALYSIS")),
        active_attempt_id=row.get("active_attempt_id"),
        source_mismatch_overridden=bool(row.get("source_mismatch_overridden", 0)),
        source_mismatch_override_by=row.get("source_mismatch_override_by"),
        source_mismatch_override_at=row.get("source_mismatch_override_at"),
        source_mismatch_override_reason=row.get("source_mismatch_override_reason"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        created_at=row.get("created_at", ""),
    )


# ── CorrelationAttempt 行映射 ──────────────────────────────


def _attempt_to_row(attempt: CorrelationAttempt) -> tuple:
    return (
        attempt.correlation_attempt_id,
        attempt.correlation_run_id,
        attempt.attempt_number,
        attempt.analysis_id,
        attempt.source_snapshot_id,
        attempt.analysis_projection_version,
        attempt.matcher_version,
        attempt.normalization_version,
        attempt.correlation_config_digest,
        attempt.status.value,
        attempt.evidence_completeness.value,
        attempt.lease_owner,
        attempt.heartbeat_at,
        attempt.lease_expires_at,
        attempt.started_at,
        attempt.completed_at,
        attempt.error_code,
        attempt.error_message,
        attempt.created_at or _utc_now_iso(),
    )


def _row_to_attempt(row: dict[str, Any]) -> CorrelationAttempt:
    return CorrelationAttempt(
        correlation_attempt_id=row["correlation_attempt_id"],
        correlation_run_id=row["correlation_run_id"],
        attempt_number=row["attempt_number"],
        analysis_id=row["analysis_id"],
        source_snapshot_id=row["source_snapshot_id"],
        analysis_projection_version=row["analysis_projection_version"],
        matcher_version=row.get("matcher_version", "v1"),
        normalization_version=row.get("normalization_version", "v1"),
        correlation_config_digest=row.get("correlation_config_digest", ""),
        status=AttemptStatus(row.get("status", "RUNNING")),
        evidence_completeness=EvidenceCompleteness(row.get("evidence_completeness", "COMPLETE")),
        lease_owner=row.get("lease_owner"),
        heartbeat_at=row.get("heartbeat_at"),
        lease_expires_at=row.get("lease_expires_at"),
        started_at=row.get("started_at", ""),
        completed_at=row.get("completed_at"),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        created_at=row.get("created_at", ""),
    )


# ── HttpRequestEvidence 行映射 ─────────────────────────────


def _http_request_to_row(req: HttpRequestEvidence) -> tuple:
    return (
        req.request_evidence_id,
        req.blackbox_run_id,
        req.task_id,
        req.step_execution_id,
        req.step_attempt,
        req.request_sequence,
        req.http_method,
        req.normalized_path,
        req.display_path,
        req.origin,
        req.resource_type,
        req.endpoint_match_eligibility.value,
        req.response_status,
        req.outcome.value,
        req.failure_code,
        req.request_owner.value,
        int(req.response_from_service_worker),
        req.page_sequence,
        req.captured_at,
        req.finished_at,
    )


def _row_to_http_request(row: dict[str, Any]) -> HttpRequestEvidence:
    return HttpRequestEvidence(
        request_evidence_id=row["request_evidence_id"],
        blackbox_run_id=row["blackbox_run_id"],
        task_id=row["task_id"],
        step_execution_id=row.get("step_execution_id"),
        step_attempt=row.get("step_attempt", 1),
        request_sequence=row["request_sequence"],
        http_method=row["http_method"],
        normalized_path=row["normalized_path"],
        display_path=row["display_path"],
        origin=row["origin"],
        resource_type=row.get("resource_type", "other"),
        endpoint_match_eligibility=CorrelationEligibility(
            row.get("endpoint_match_eligibility", "CONFIRMED_ELIGIBLE")
        ),
        response_status=row.get("response_status"),
        outcome=RequestOutcome(row.get("outcome", "COMPLETED")),
        failure_code=row.get("failure_code"),
        request_owner=RequestOwner(row.get("request_owner", "FRAME")),
        response_from_service_worker=bool(row.get("response_from_service_worker", 0)),
        page_sequence=row.get("page_sequence", 0),
        captured_at=row["captured_at"],
        finished_at=row.get("finished_at"),
    )


# ── EndpointEvidence 行映射 ────────────────────────────────


def _ee_to_row(ee: EndpointEvidence) -> tuple:
    return (
        ee.endpoint_evidence_id,
        ee.correlation_run_id,
        ee.correlation_attempt_id,
        ee.request_evidence_id,
        ee.resolution_status.value,
        ee.match_strategy.value,
        ee.confidence.value,
        ee.matched_endpoint_id,
        ee.match_reason_code,
        ee.matcher_version,
        ee.normalization_version,
        ee.candidate_count,
        ee.created_at or _utc_now_iso(),
    )


# ── Repository ─────────────────────────────────────────────


class CorrelationRepository:
    """blackbox_runs, correlation_runs, correlation_attempts 及证据表读写。"""

    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    # ══════════════════════════════════════════════════════════
    # BlackboxRun
    # ══════════════════════════════════════════════════════════

    def create_blackbox_run(self, run: BlackboxRun) -> BlackboxRun:
        with self._pool.tx() as conn:
            conn.execute(
                """INSERT INTO blackbox_runs (
                    blackbox_run_id, task_id, attempt, status, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                _blackbox_run_to_row(run),
            )
        return run

    def get_blackbox_run(self, blackbox_run_id: str) -> BlackboxRun | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM blackbox_runs WHERE blackbox_run_id = ?",
                (blackbox_run_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_blackbox_run(dict(row))

    def list_blackbox_runs_by_task(self, task_id: str) -> list[BlackboxRun]:
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM blackbox_runs WHERE task_id = ? ORDER BY started_at DESC",
                (task_id,),
            ).fetchall()
        return [_row_to_blackbox_run(dict(r)) for r in rows]

    def update_blackbox_run_status(
        self,
        blackbox_run_id: str,
        status: str,
        completed_at: str | None = None,
    ) -> None:
        sets = ["status = ?"]
        values: list[Any] = [status]
        if completed_at is not None:
            sets.append("completed_at = ?")
            values.append(completed_at)
        values.append(blackbox_run_id)
        with self._pool.tx() as conn:
            conn.execute(
                f"UPDATE blackbox_runs SET {', '.join(sets)} WHERE blackbox_run_id = ?",
                values,
            )

    # ══════════════════════════════════════════════════════════
    # CorrelationRun
    # ══════════════════════════════════════════════════════════

    def create_correlation_run(self, run: CorrelationRun) -> CorrelationRun:
        with self._pool.tx() as conn:
            conn.execute(
                """INSERT INTO correlation_runs (
                    correlation_run_id, project_id, blackbox_run_id,
                    desired_source_snapshot_id, desired_analysis_config_digest,
                    required_analyzer_version, allow_partial_analysis,
                    analysis_id, bound_source_snapshot_id, analysis_projection_version,
                    correlation_config_digest, matcher_version, normalization_version,
                    supersedes_correlation_run_id,
                    source_alignment_status, status, active_attempt_id,
                    source_mismatch_overridden, source_mismatch_override_by,
                    source_mismatch_override_at, source_mismatch_override_reason,
                    started_at, completed_at, error_code, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _correlation_run_to_row(run),
            )
        return run

    def get_correlation_run(self, correlation_run_id: str) -> CorrelationRun | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM correlation_runs WHERE correlation_run_id = ?",
                (correlation_run_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_correlation_run(dict(row))

    def get_correlation_run_by_blackbox(self, blackbox_run_id: str) -> CorrelationRun | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM correlation_runs WHERE blackbox_run_id = ? ORDER BY created_at DESC LIMIT 1",
                (blackbox_run_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_correlation_run(dict(row))

    def list_by_analysis_ids(self, analysis_ids: list[str]) -> list[CorrelationRun]:
        """通过白盒 analysis_id 列表查找关联运行（白盒任务→关联证据入口）。"""
        if not analysis_ids:
            return []
        placeholders = ", ".join(["?"] * len(analysis_ids))
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM correlation_runs WHERE analysis_id IN ({placeholders}) "
                "ORDER BY created_at DESC",
                analysis_ids,
            ).fetchall()
        return [_row_to_correlation_run(dict(r)) for r in rows]

    def set_status(self, correlation_run_id: str, status: CorrelationRunStatus) -> None:
        with self._pool.tx() as conn:
            conn.execute(
                "UPDATE correlation_runs SET status = ? WHERE correlation_run_id = ?",
                (status.value, correlation_run_id),
            )

    def find_waiting_analysis(
        self,
        desired_source_snapshot_id: str,
        *,
        project_id: str | None = None,
    ) -> list[CorrelationRun]:
        """查找 WAITING_ANALYSIS 的关联运行。

        仅匹配 desired_source_snapshot_id 精确一致的运行。
        空字符串也按精确值处理；是否用它承接“黑盒先启动、白盒后完成”
        的回退绑定，由应用编排层显式决定。
        """
        with self._pool.ro_conn() as conn:
            conditions = [
                "desired_source_snapshot_id = ?",
                "status = 'WAITING_ANALYSIS'",
            ]
            params: list[Any] = [desired_source_snapshot_id]
            if project_id:
                conditions.append("project_id = ?")
                params.append(project_id)
            query = (
                "SELECT * FROM correlation_runs WHERE "
                + " AND ".join(conditions)
                + " ORDER BY created_at"
            )
            rows = conn.execute(query, params).fetchall()
        return [_row_to_correlation_run(dict(r)) for r in rows]

    def bind_analysis(
        self,
        correlation_run_id: str,
        analysis_id: str,
        bound_source_snapshot_id: str,
        analysis_projection_version: int,
        source_alignment_status: str,
        *,
        source_mismatch_overridden: bool = False,
        source_mismatch_override_by: str | None = None,
        source_mismatch_override_at: str | None = None,
        source_mismatch_override_reason: str | None = None,
    ) -> None:
        with self._pool.tx() as conn:
            conn.execute(
                """UPDATE correlation_runs
                   SET analysis_id = ?, bound_source_snapshot_id = ?,
                       desired_source_snapshot_id =
                           CASE WHEN desired_source_snapshot_id = ''
                           THEN ? ELSE desired_source_snapshot_id END,
                       analysis_projection_version = ?, source_alignment_status = ?,
                       source_mismatch_overridden = ?,
                       source_mismatch_override_by = ?,
                       source_mismatch_override_at = ?,
                       source_mismatch_override_reason = ?
                   WHERE correlation_run_id = ? AND analysis_id IS NULL""",
                (
                    analysis_id,
                    bound_source_snapshot_id,
                    bound_source_snapshot_id,
                    analysis_projection_version,
                    source_alignment_status,
                    int(source_mismatch_overridden),
                    source_mismatch_override_by,
                    source_mismatch_override_at,
                    source_mismatch_override_reason,
                    correlation_run_id,
                ),
            )

    # ══════════════════════════════════════════════════════════
    # CorrelationAttempt
    # ══════════════════════════════════════════════════════════

    def create_attempt(self, attempt: CorrelationAttempt) -> CorrelationAttempt:
        with self._pool.tx() as conn:
            conn.execute(
                """INSERT INTO correlation_attempts (
                    correlation_attempt_id, correlation_run_id, attempt_number,
                    analysis_id, source_snapshot_id, analysis_projection_version,
                    matcher_version, normalization_version, correlation_config_digest,
                    status, evidence_completeness,
                    lease_owner, heartbeat_at, lease_expires_at,
                    started_at, completed_at, error_code, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _attempt_to_row(attempt),
            )
        return attempt

    def get_attempt(self, attempt_id: str) -> CorrelationAttempt | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM correlation_attempts WHERE correlation_attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_attempt(dict(row))

    def list_attempts_by_run(self, correlation_run_id: str) -> list[CorrelationAttempt]:
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM correlation_attempts WHERE correlation_run_id = ? "
                "ORDER BY attempt_number DESC",
                (correlation_run_id,),
            ).fetchall()
        return [_row_to_attempt(dict(r)) for r in rows]

    def list_running_attempts_with_expired_lease(self) -> list[CorrelationAttempt]:
        now = _utc_now_iso()
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM correlation_attempts WHERE status = 'RUNNING' AND lease_expires_at < ?",
                (now,),
            ).fetchall()
        return [_row_to_attempt(dict(r)) for r in rows]

    def abort_attempt(self, attempt_id: str) -> None:
        with self._pool.tx() as conn:
            conn.execute(
                "UPDATE correlation_attempts SET status = 'ABORTED', completed_at = ? "
                "WHERE correlation_attempt_id = ?",
                (_utc_now_iso(), attempt_id),
            )

    # ══════════════════════════════════════════════════════════
    # CAS 原子操作
    # ══════════════════════════════════════════════════════════

    def claim_and_create_attempt(
        self,
        correlation_run_id: str,
        worker_id: str,
    ) -> CorrelationAttempt | None:
        """单事务 CAS READY→RUNNING + INSERT attempt。"""
        with self._pool.tx() as conn:
            cursor = conn.execute(
                """UPDATE correlation_runs SET status = 'RUNNING', started_at = ?
                   WHERE correlation_run_id = ? AND status = 'READY'""",
                (_utc_now_iso(), correlation_run_id),
            )
            if cursor.rowcount != 1:
                return None

            run_row = conn.execute(
                "SELECT * FROM correlation_runs WHERE correlation_run_id = ?",
                (correlation_run_id,),
            ).fetchone()
            if run_row is None:
                return None
            run = _row_to_correlation_run(dict(run_row))

            existing = conn.execute(
                "SELECT MAX(attempt_number) FROM correlation_attempts WHERE correlation_run_id = ?",
                (correlation_run_id,),
            ).fetchone()
            attempt_number = (existing[0] or 0) + 1

            attempt_id = _new_id("ca")
            attempt = CorrelationAttempt(
                correlation_attempt_id=attempt_id,
                correlation_run_id=correlation_run_id,
                attempt_number=attempt_number,
                analysis_id=run.analysis_id or "",
                source_snapshot_id=run.bound_source_snapshot_id or "",
                analysis_projection_version=run.analysis_projection_version or 0,
                matcher_version=run.matcher_version,
                normalization_version=run.normalization_version,
                correlation_config_digest=run.correlation_config_digest,
                status=AttemptStatus.RUNNING,
                lease_owner=worker_id,
                heartbeat_at=_utc_now_iso(),
                lease_expires_at=_lease_expiry(),
                started_at=_utc_now_iso(),
                created_at=_utc_now_iso(),
            )
            conn.execute(
                """INSERT INTO correlation_attempts (
                    correlation_attempt_id, correlation_run_id, attempt_number,
                    analysis_id, source_snapshot_id, analysis_projection_version,
                    matcher_version, normalization_version, correlation_config_digest,
                    status, evidence_completeness,
                    lease_owner, heartbeat_at, lease_expires_at,
                    started_at, completed_at, error_code, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _attempt_to_row(attempt),
            )

            return attempt

    def complete_and_activate_attempt(
        self,
        attempt_id: str,
        status: AttemptStatus,
        completeness: EvidenceCompleteness = EvidenceCompleteness.COMPLETE,
    ) -> None:
        """单事务完成 Attempt 并原子切换到 active。"""
        with self._pool.tx() as conn:
            cr_row = conn.execute(
                """SELECT correlation_run_id FROM correlation_attempts
                   WHERE correlation_attempt_id = ?""",
                (attempt_id,),
            ).fetchone()
            if cr_row is None:
                return
            cr_id = cr_row["correlation_run_id"]

            conn.execute(
                """UPDATE correlation_attempts
                   SET status = ?, evidence_completeness = ?, completed_at = ?
                   WHERE correlation_attempt_id = ?""",
                (status.value, completeness.value, _utc_now_iso(), attempt_id),
            )

            cr_status = (
                CorrelationRunStatus.SUCCEEDED
                if status == AttemptStatus.SUCCEEDED
                else status.value
            )

            if status == AttemptStatus.FAILED:
                # FAILED 不发布：不更新 active_attempt_id，保留旧 active 结果可见
                conn.execute(
                    """UPDATE correlation_runs
                       SET status = ?, completed_at = ?
                       WHERE correlation_run_id = ?""",
                    (cr_status, _utc_now_iso(), cr_id),
                )
            else:
                conn.execute(
                    """UPDATE correlation_runs
                       SET active_attempt_id = ?, status = ?, completed_at = ?
                       WHERE correlation_run_id = ?""",
                    (attempt_id, cr_status, _utc_now_iso(), cr_id),
                )

    # ══════════════════════════════════════════════════════════
    # HttpRequestEvidence
    # ══════════════════════════════════════════════════════════

    def insert_request_batch(self, items: list[HttpRequestEvidence]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO http_request_evidence (
                    request_evidence_id, blackbox_run_id, task_id, step_execution_id,
                    step_attempt, request_sequence, http_method,
                    normalized_path, display_path, origin, resource_type,
                    endpoint_match_eligibility, response_status, outcome, failure_code,
                    request_owner, response_from_service_worker, page_sequence,
                    captured_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [_http_request_to_row(item) for item in items],
            )

    def list_requests_by_blackbox_run(
        self,
        blackbox_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[HttpRequestEvidence], int]:
        with self._pool.ro_conn() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM http_request_evidence WHERE blackbox_run_id = ?",
                (blackbox_run_id,),
            ).fetchone()
            total = total_row["cnt"] if total_row else 0
            rows = conn.execute(
                "SELECT * FROM http_request_evidence WHERE blackbox_run_id = ? "
                "ORDER BY request_sequence LIMIT ? OFFSET ?",
                (blackbox_run_id, limit, offset),
            ).fetchall()
        return [_row_to_http_request(dict(r)) for r in rows], total

    def list_eligible_requests(
        self,
        blackbox_run_id: str,
    ) -> list[HttpRequestEvidence]:
        """获取 CONFIRMED_ELIGIBLE 或 ATTEMPT_ONLY 的请求。"""
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM http_request_evidence
                   WHERE blackbox_run_id = ?
                     AND endpoint_match_eligibility IN ('CONFIRMED_ELIGIBLE', 'ATTEMPT_ONLY')
                   ORDER BY request_sequence""",
                (blackbox_run_id,),
            ).fetchall()
        return [_row_to_http_request(dict(r)) for r in rows]

    def list_unmatched_requests(
        self,
        correlation_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[HttpRequestEvidence], int]:
        """获取 resolution_status='UNMATCHED' 的请求（通过 endpoint_evidence 状态过滤）。

        限定 active_attempt_id，避免重试/重算后混入旧 Attempt 的记录。
        """
        cr = self.get_correlation_run(correlation_run_id)
        if cr is None:
            return [], 0
        bb_id = cr.blackbox_run_id
        active_attempt_id = cr.active_attempt_id
        if active_attempt_id is None:
            return [], 0
        with self._pool.ro_conn() as conn:
            total_row = conn.execute(
                """SELECT COUNT(*) AS cnt FROM http_request_evidence hre
                   INNER JOIN endpoint_evidence ee ON ee.request_evidence_id = hre.request_evidence_id
                     AND ee.correlation_attempt_id = ?
                   WHERE hre.blackbox_run_id = ? AND ee.resolution_status = 'UNMATCHED'""",
                (active_attempt_id, bb_id),
            ).fetchone()
            total = total_row["cnt"] if total_row else 0
            rows = conn.execute(
                """SELECT hre.* FROM http_request_evidence hre
                   INNER JOIN endpoint_evidence ee ON ee.request_evidence_id = hre.request_evidence_id
                     AND ee.correlation_attempt_id = ?
                   WHERE hre.blackbox_run_id = ? AND ee.resolution_status = 'UNMATCHED'
                   ORDER BY hre.request_sequence LIMIT ? OFFSET ?""",
                (active_attempt_id, bb_id, limit, offset),
            ).fetchall()
        return [_row_to_http_request(dict(r)) for r in rows], total

    # ══════════════════════════════════════════════════════════
    # EndpointEvidence + 关系表
    # ══════════════════════════════════════════════════════════

    def insert_evidence_batch(self, items: list[EndpointEvidence]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT INTO endpoint_evidence (
                    endpoint_evidence_id, correlation_run_id, correlation_attempt_id,
                    request_evidence_id, resolution_status, match_strategy, confidence,
                    matched_endpoint_id, match_reason_code, matcher_version,
                    normalization_version, candidate_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [_ee_to_row(item) for item in items],
            )

    def insert_candidates_batch(self, items: list[EndpointEvidenceCandidate]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO endpoint_evidence_candidates (
                    endpoint_evidence_id, endpoint_id, candidate_rank,
                    match_strategy, confidence, reason_code, selected
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        c.endpoint_evidence_id,
                        c.endpoint_id,
                        c.candidate_rank,
                        c.match_strategy.value,
                        c.confidence.value,
                        c.reason_code,
                        int(c.selected),
                    )
                    for c in items
                ],
            )

    def insert_flows_batch(self, items: list[EndpointEvidenceFlow]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO endpoint_evidence_flows (
                    endpoint_evidence_id, execution_flow_id, relation_type,
                    endpoint_method_snapshot, endpoint_path_snapshot,
                    controller_snapshot, flow_name_snapshot, source_location_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        f.endpoint_evidence_id,
                        f.execution_flow_id,
                        f.relation_type,
                        f.endpoint_method_snapshot,
                        f.endpoint_path_snapshot,
                        f.controller_snapshot,
                        f.flow_name_snapshot,
                        f.source_location_snapshot,
                    )
                    for f in items
                ],
            )

    def list_evidence_by_attempt(
        self,
        attempt_id: str,
        *,
        resolution_status: str | None = None,
        match_strategy: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._pool.ro_conn() as conn:
            where = ["ee.correlation_attempt_id = ?"]
            params: list[Any] = [attempt_id]
            if resolution_status is not None:
                where.append("ee.resolution_status = ?")
                params.append(resolution_status)
            if match_strategy is not None:
                where.append("ee.match_strategy = ?")
                params.append(match_strategy)
            clause = " AND ".join(where)
            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM endpoint_evidence ee WHERE {clause}",
                params,
            ).fetchone()
            total = total_row["cnt"] if total_row else 0
            rows = conn.execute(
                f"""SELECT ee.*, hre.http_method, hre.normalized_path AS request_path,
                           hre.display_path, hre.origin, hre.resource_type
                    FROM endpoint_evidence ee
                    JOIN http_request_evidence hre ON hre.request_evidence_id = ee.request_evidence_id
                    WHERE {clause}
                    ORDER BY ee.created_at LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
        return [dict(r) for r in rows], total

    def get_summary(self, correlation_run_id: str) -> CorrelationSummary:
        cr = self.get_correlation_run(correlation_run_id)
        attempt_id = cr.active_attempt_id if cr else None

        summary = CorrelationSummary(
            correlation_run_id=correlation_run_id,
            status=cr.status.value if cr else "",
            source_alignment_status=cr.source_alignment_status.value if cr else "",
            matcher_version=cr.matcher_version if cr else "v1",
            normalization_version=cr.normalization_version if cr else "v1",
        )

        if cr is None:
            return summary

        bb_id = cr.blackbox_run_id

        with self._pool.ro_conn() as conn:
            # ── 采集质量 ──
            cq = conn.execute(
                "SELECT * FROM http_capture_quality WHERE blackbox_run_id = ?",
                (bb_id,),
            ).fetchone()
            if cq:
                summary.cross_origin_filtered_count = cq["filtered_cross_origin"] or 0
                summary.resource_filtered_count = cq["filtered_by_resource_type"] or 0
                summary.dropped_request_count = (
                    (cq["dropped_pending_limit"] or 0)
                    + (cq["dropped_run_limit"] or 0)
                    + (cq["dropped_writer_queue_limit"] or 0)
                )
                summary.failed_capture_count = cq["persistence_failed"] or 0
                summary.captured_request_count = cq["persisted_count"] or 0

        # ── 请求证据总数（避免采集质量未持久化时为零）──
        if summary.captured_request_count == 0:
            with self._pool.ro_conn() as conn:
                total_row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM http_request_evidence WHERE blackbox_run_id = ?",
                    (bb_id,),
                ).fetchone()
                summary.captured_request_count = total_row["cnt"] if total_row else 0

        # ── 可关联请求 ──
        eligible_reqs = self.list_eligible_requests(bb_id)
        summary.correlatable_request_count = len(eligible_reqs)

        if attempt_id is None:
            return summary

        with self._pool.ro_conn() as conn:
            # ── 端点证据分组计数 ──
            # ATTEMPT_ONLY 请求也参与匹配并生成证据，但不计入 confirmed 类统计
            ee_stats = conn.execute(
                """SELECT ee.resolution_status, ee.match_strategy,
                          COUNT(*) AS cnt,
                          SUM(CASE WHEN hre.endpoint_match_eligibility = 'ATTEMPT_ONLY'
                              THEN 1 ELSE 0 END) AS attempt_only_cnt
                   FROM endpoint_evidence ee
                   JOIN http_request_evidence hre
                     ON hre.request_evidence_id = ee.request_evidence_id
                   WHERE ee.correlation_attempt_id = ?
                   GROUP BY ee.resolution_status, ee.match_strategy""",
                (attempt_id,),
            ).fetchall()
            for row in ee_stats:
                rs = row["resolution_status"]
                ms = row["match_strategy"]
                cnt = row["cnt"]
                attempt_only = row["attempt_only_cnt"]
                confirmed_cnt = cnt - attempt_only
                if rs == "UNIQUE" and ms in ("EXACT", "TEMPLATE"):
                    summary.confirmed_matched_request_count += confirmed_cnt
                elif rs == "AMBIGUOUS":
                    summary.ambiguous_request_count += cnt
                elif rs == "UNMATCHED":
                    summary.unmatched_request_count += cnt
                elif ms == "PATH_ONLY":
                    summary.method_mismatch_candidate_count += cnt

            # ── 端点触达统计 ──
            confirmed_touch = conn.execute(
                """SELECT COUNT(DISTINCT ee.matched_endpoint_id) AS cnt
                   FROM endpoint_evidence ee
                   JOIN http_request_evidence hre
                     ON hre.request_evidence_id = ee.request_evidence_id
                   WHERE ee.correlation_attempt_id = ?
                     AND ee.resolution_status = 'UNIQUE'
                     AND ee.match_strategy IN ('EXACT', 'TEMPLATE')
                     AND hre.endpoint_match_eligibility != 'ATTEMPT_ONLY'
                     AND ee.matched_endpoint_id IS NOT NULL""",
                (attempt_id,),
            ).fetchone()
            summary.confirmed_touched_endpoint_count = (
                confirmed_touch["cnt"] if confirmed_touch else 0
            )

            candidate_touch = conn.execute(
                """SELECT COUNT(DISTINCT eec.endpoint_id) AS cnt
                   FROM endpoint_evidence_candidates eec
                   JOIN endpoint_evidence ee ON ee.endpoint_evidence_id = eec.endpoint_evidence_id
                   WHERE ee.correlation_attempt_id = ?""",
                (attempt_id,),
            ).fetchone()
            summary.candidate_touched_endpoint_count = (
                candidate_touch["cnt"] if candidate_touch else 0
            )

            # ── 端点总数（来自分析投影）──
            if cr.analysis_id:
                ep_total = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM analysis_endpoints WHERE analysis_id = ?",
                    (cr.analysis_id,),
                ).fetchone()
                summary.total_endpoint_count = ep_total["cnt"] if ep_total else 0
                summary.uncovered_endpoint_count = max(
                    0,
                    summary.total_endpoint_count
                    - summary.confirmed_touched_endpoint_count
                    - summary.candidate_touched_endpoint_count,
                )

            # ── ATTEMPT_ONLY 证据数 ──
            attempted = conn.execute(
                """SELECT COUNT(*) AS cnt FROM http_request_evidence
                   WHERE blackbox_run_id = ? AND endpoint_match_eligibility = 'ATTEMPT_ONLY'""",
                (bb_id,),
            ).fetchone()
            summary.attempted_evidence_count = attempted["cnt"] if attempted else 0

            # ── Finding 统计 ──
            fe_stats = conn.execute(
                """SELECT best_relation_type, COUNT(*) AS cnt
                   FROM finding_evidence
                   WHERE correlation_attempt_id = ?
                   GROUP BY best_relation_type""",
                (attempt_id,),
            ).fetchall()
            for row in fe_stats:
                rt = row["best_relation_type"]
                cnt = row["cnt"]
                summary.total_finding_count += cnt
                if rt in ("DIRECT_HANDLER", "STATIC_REACHABLE", "FLOW_MEMBER"):
                    summary.confirmed_related_finding_count += cnt
                elif rt == "UNKNOWN":
                    summary.unrelated_finding_count += cnt

            # Attempt 完整性
            attempt = conn.execute(
                "SELECT evidence_completeness FROM correlation_attempts WHERE correlation_attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if attempt:
                summary.evidence_completeness = attempt["evidence_completeness"]

        return summary

    # ══════════════════════════════════════════════════════════
    # FindingEvidence
    # ══════════════════════════════════════════════════════════

    def insert_finding_evidence_batch(self, items: list[FindingEvidence]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO finding_evidence (
                    finding_evidence_id, correlation_attempt_id, finding_id,
                    best_relation_type, minimum_call_distance,
                    confirmed_request_count, candidate_request_count,
                    finding_rule_id_snapshot, finding_location_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        fe.finding_evidence_id,
                        fe.correlation_attempt_id,
                        fe.finding_id,
                        fe.best_relation_type.value,
                        fe.minimum_call_distance,
                        fe.confirmed_request_count,
                        fe.candidate_request_count,
                        fe.finding_rule_id_snapshot,
                        fe.finding_location_snapshot,
                    )
                    for fe in items
                ],
            )

    def insert_finding_links_batch(self, items: list[FindingEvidenceLink]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO finding_evidence_links (
                    finding_evidence_id, correlation_attempt_id, endpoint_evidence_id,
                    endpoint_id, execution_flow_id, relation_type, call_distance
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        fl.finding_evidence_id,
                        fl.correlation_attempt_id,
                        fl.endpoint_evidence_id,
                        fl.endpoint_id,
                        fl.execution_flow_id,
                        fl.relation_type.value
                        if hasattr(fl.relation_type, "value")
                        else str(fl.relation_type),
                        fl.call_distance,
                    )
                    for fl in items
                ],
            )

    def list_finding_evidence(
        self,
        correlation_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        cr = self.get_correlation_run(correlation_run_id)
        if cr is None or cr.active_attempt_id is None:
            return [], 0
        attempt_id = cr.active_attempt_id
        with self._pool.ro_conn() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM finding_evidence WHERE correlation_attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            total = total_row["cnt"] if total_row else 0
            rows = conn.execute(
                "SELECT * FROM finding_evidence WHERE correlation_attempt_id = ? "
                "ORDER BY confirmed_request_count DESC LIMIT ? OFFSET ?",
                (attempt_id, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows], total

    # ══════════════════════════════════════════════════════════
    # Attempt 明细表
    # ══════════════════════════════════════════════════════════

    def insert_attempt_reasons_batch(self, items: list[CorrelationAttemptReason]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO correlation_attempt_reasons (
                    correlation_attempt_id, reason_code, detail
                ) VALUES (?, ?, ?)""",
                [(r.correlation_attempt_id, r.reason_code.value, r.detail) for r in items],
            )

    def insert_attempt_diagnostics_batch(self, items: list[CorrelationAttemptDiagnostic]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO correlation_attempt_diagnostics (
                    correlation_attempt_id, diagnostic_code, detail
                ) VALUES (?, ?, ?)""",
                [(d.correlation_attempt_id, d.diagnostic_code.value, d.detail) for d in items],
            )

    # ══════════════════════════════════════════════════════════
    # CaptureQuality
    # ══════════════════════════════════════════════════════════

    def upsert_capture_quality(self, quality: CaptureQuality) -> None:
        with self._pool.tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO http_capture_quality (
                    blackbox_run_id, total_observed, accepted_started, persisted_count,
                    filtered_by_resource_type, filtered_cross_origin, filtered_by_method,
                    filtered_websocket_count, filtered_path_too_long,
                    dropped_pending_limit, dropped_run_limit, dropped_writer_queue_limit,
                    writer_retry_count, writer_failed_batch_count, persistence_failed,
                    truncated, truncation_reason, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    quality.blackbox_run_id,
                    quality.total_observed,
                    quality.accepted_started,
                    quality.persisted_count,
                    quality.filtered_by_resource_type,
                    quality.filtered_cross_origin,
                    quality.filtered_by_method,
                    quality.filtered_websocket_count,
                    quality.filtered_path_too_long,
                    quality.dropped_pending_limit,
                    quality.dropped_run_limit,
                    quality.dropped_writer_queue_limit,
                    quality.writer_retry_count,
                    quality.writer_failed_batch_count,
                    quality.persistence_failed,
                    int(quality.truncated),
                    quality.truncation_reason,
                    quality.updated_at or _utc_now_iso(),
                ),
            )

    # ══════════════════════════════════════════════════════════
    # Uncovered Endpoints
    # ══════════════════════════════════════════════════════════

    def list_uncovered_endpoints(
        self,
        correlation_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        """获取未被确认触达的端点（无 UNIQUE+EXACT/TEMPLATE 证据）。"""
        cr = self.get_correlation_run(correlation_run_id)
        if cr is None or cr.analysis_id is None or cr.active_attempt_id is None:
            return [], 0

        with self._pool.ro_conn() as conn:
            total_row = conn.execute(
                """SELECT COUNT(*) AS cnt FROM analysis_endpoints ae
                   WHERE ae.analysis_id = ?
                     AND ae.endpoint_id NOT IN (
                         SELECT ee.matched_endpoint_id FROM endpoint_evidence ee
                         WHERE ee.correlation_attempt_id = ?
                           AND ee.resolution_status = 'UNIQUE'
                           AND ee.match_strategy IN ('EXACT', 'TEMPLATE')
                           AND ee.matched_endpoint_id IS NOT NULL
                     )""",
                (cr.analysis_id, cr.active_attempt_id),
            ).fetchone()
            total = total_row["cnt"] if total_row else 0
            rows = conn.execute(
                """SELECT * FROM analysis_endpoints ae
                   WHERE ae.analysis_id = ?
                     AND ae.endpoint_id NOT IN (
                         SELECT ee.matched_endpoint_id FROM endpoint_evidence ee
                         WHERE ee.correlation_attempt_id = ?
                           AND ee.resolution_status = 'UNIQUE'
                           AND ee.match_strategy IN ('EXACT', 'TEMPLATE')
                           AND ee.matched_endpoint_id IS NOT NULL
                     )
                   ORDER BY ae.normalized_path_template ASC, ae.http_method ASC
                   LIMIT ? OFFSET ?""",
                (cr.analysis_id, cr.active_attempt_id, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows], total

    # ══════════════════════════════════════════════════════════
    # 批量查询辅助（供 application 层组装 API 响应）
    # ══════════════════════════════════════════════════════════

    # SQLite 默认编译期参数上限 999，留安全余量
    _BATCH_QUERY_MAX_IDS = 900

    def _check_batch_ids(self, ids: list[str], label: str) -> None:
        if len(ids) > self._BATCH_QUERY_MAX_IDS:
            raise ValueError(
                f"{label} 批量查询 ID 数量超出限制: "
                f"{len(ids)} > {CorrelationRepository._BATCH_QUERY_MAX_IDS}"
            )

    def batch_get_candidates(self, evidence_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """按 evidence_id 批量查询候选端点。"""
        if not evidence_ids:
            return {}
        self._check_batch_ids(evidence_ids, "candidates")
        with self._pool.ro_conn() as conn:
            placeholders = ",".join("?" for _ in evidence_ids)
            rows = conn.execute(
                f"SELECT * FROM endpoint_evidence_candidates "
                f"WHERE endpoint_evidence_id IN ({placeholders}) "
                f"ORDER BY candidate_rank",
                evidence_ids,
            ).fetchall()
        result: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            d = dict(r)
            eid = d["endpoint_evidence_id"]
            result.setdefault(eid, []).append(d)
        return result

    def batch_get_flows(self, evidence_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """按 evidence_id 批量查询调用流关联。"""
        if not evidence_ids:
            return {}
        self._check_batch_ids(evidence_ids, "flows")
        with self._pool.ro_conn() as conn:
            placeholders = ",".join("?" for _ in evidence_ids)
            rows = conn.execute(
                f"SELECT * FROM endpoint_evidence_flows "
                f"WHERE endpoint_evidence_id IN ({placeholders})",
                evidence_ids,
            ).fetchall()
        result: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            d = dict(r)
            eid = d["endpoint_evidence_id"]
            result.setdefault(eid, []).append(d)
        return result

    def batch_get_endpoint_details(self, endpoint_ids: list[str]) -> dict[str, dict[str, Any]]:
        """按 endpoint_id 批量查询端点详情。"""
        if not endpoint_ids:
            return {}
        self._check_batch_ids(endpoint_ids, "endpoint_details")
        with self._pool.ro_conn() as conn:
            placeholders = ",".join("?" for _ in endpoint_ids)
            rows = conn.execute(
                f"SELECT * FROM analysis_endpoints WHERE endpoint_id IN ({placeholders})",
                endpoint_ids,
            ).fetchall()
        return {r["endpoint_id"]: dict(r) for r in rows}

    def batch_get_finding_details(self, finding_ids: list[str]) -> dict[str, dict[str, Any]]:
        """按 finding_id 批量查询发现项详情。"""
        if not finding_ids:
            return {}
        self._check_batch_ids(finding_ids, "finding_details")
        with self._pool.ro_conn() as conn:
            placeholders = ",".join("?" for _ in finding_ids)
            rows = conn.execute(
                f"SELECT * FROM findings WHERE finding_id IN ({placeholders})",
                finding_ids,
            ).fetchall()
        return {r["finding_id"]: dict(r) for r in rows}

    # ══════════════════════════════════════════════════════════
    # 崩溃恢复
    # ══════════════════════════════════════════════════════════

    def recover_stale_attempts(self) -> list[CorrelationAttempt]:
        """将 lease 过期的 RUNNING Attempt 标记为 ABORTED，并回退 Run 状态。"""
        stale = self.list_running_attempts_with_expired_lease()
        for attempt in stale:
            self.abort_attempt(attempt.correlation_attempt_id)
            # 检查重试资格
            cr = self.get_correlation_run(attempt.correlation_run_id)
            if cr is not None:
                if cr.status in (CorrelationRunStatus.RUNNING,):
                    new_status = (
                        CorrelationRunStatus.READY
                        if cr.analysis_id is not None
                        else CorrelationRunStatus.WAITING_ANALYSIS
                    )
                    # 回退状态并清除 active_attempt_id 和 completed_at：
                    # claim 不再设置 active_attempt_id，完成时才原子发布，
                    # 因此恢复时必须清除旧的 active_attempt_id 避免指向 ABORTED attempt。
                    # 同时清除 completed_at，避免 READY 状态下残留旧完成时间戳。
                    with self._pool.tx() as conn:
                        conn.execute(
                            """UPDATE correlation_runs
                               SET status = ?, active_attempt_id = NULL,
                                   completed_at = NULL
                               WHERE correlation_run_id = ?""",
                            (new_status.value, cr.correlation_run_id),
                        )
        return stale
