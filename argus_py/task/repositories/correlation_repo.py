"""correlation_runs 与 correlation_attempts 表读写（含 CAS 认领与崩溃恢复）。

证据侧表（http_request_evidence / endpoint_evidence / finding_evidence 等）
见 ``evidence_repo``；blackbox_runs 与采集质量见 ``blackbox_repo``。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from argus_py.core.constants import utc_now_iso as _utc_now_iso
from argus_py.correlation.enums import (
    AttemptStatus,
    CorrelationRunStatus,
    EvidenceCompleteness,
)
from argus_py.correlation.models import (
    CorrelationAttempt,
    CorrelationRun,
    CorrelationSummary,
)
from argus_py.infra.db import DbPool
from argus_py.task.repositories.mappers import (
    attempt_to_row,
    correlation_run_to_row,
    row_to_attempt,
    row_to_correlation_run,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex[:12]}"


_LEASE_DURATION_SECONDS = 300


def _lease_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=_LEASE_DURATION_SECONDS)).isoformat()


class CorrelationRepository:
    """correlation_runs 与 correlation_attempts 及 CAS 状态机读写。"""

    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

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
                correlation_run_to_row(run),
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
        return row_to_correlation_run(dict(row))

    def get_correlation_run_by_blackbox(self, blackbox_run_id: str) -> CorrelationRun | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM correlation_runs WHERE blackbox_run_id = ? ORDER BY created_at DESC LIMIT 1",
                (blackbox_run_id,),
            ).fetchone()
        if row is None:
            return None
        return row_to_correlation_run(dict(row))

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
        return [row_to_correlation_run(dict(r)) for r in rows]

    def list_by_blackbox_run_ids(self, blackbox_run_ids: list[str]) -> list[CorrelationRun]:
        """通过黑盒 blackbox_run_id 列表批量查找关联运行（消除路径 1 的 N+1）。

        每个 blackbox_run_id 只返回最新的一条（ROW_NUMBER 按 created_at DESC 取
        rn=1），与原先逐条的 ``get_correlation_run_by_blackbox``（ORDER BY created_at
        DESC LIMIT 1）语义一致——重算产生的 supersede 历史 run 不返回。
        """
        if not blackbox_run_ids:
            return []
        placeholders = ", ".join(["?"] * len(blackbox_run_ids))
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY blackbox_run_id ORDER BY created_at DESC
                        ) AS rn
                        FROM correlation_runs
                        WHERE blackbox_run_id IN ({placeholders})
                    ) WHERE rn = 1
                    ORDER BY created_at DESC""",
                blackbox_run_ids,
            ).fetchall()
        return [row_to_correlation_run(dict(r)) for r in rows]

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
        return [row_to_correlation_run(dict(r)) for r in rows]

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
                attempt_to_row(attempt),
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
        return row_to_attempt(dict(row))

    def list_attempts_by_run(self, correlation_run_id: str) -> list[CorrelationAttempt]:
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM correlation_attempts WHERE correlation_run_id = ? "
                "ORDER BY attempt_number DESC",
                (correlation_run_id,),
            ).fetchall()
        return [row_to_attempt(dict(r)) for r in rows]

    def list_running_attempts_with_expired_lease(self) -> list[CorrelationAttempt]:
        now = _utc_now_iso()
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM correlation_attempts WHERE status = 'RUNNING' AND lease_expires_at < ?",
                (now,),
            ).fetchall()
        return [row_to_attempt(dict(r)) for r in rows]

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
            run = row_to_correlation_run(dict(run_row))

            existing = conn.execute(
                "SELECT MAX(attempt_number) AS max_num FROM correlation_attempts "
                "WHERE correlation_run_id = ?",
                (correlation_run_id,),
            ).fetchone()
            attempt_number = (existing["max_num"] or 0) + 1 if existing else 1

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
                attempt_to_row(attempt),
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
    # 汇总读模型（跨 evidence/投影表的聚合查询）
    # ══════════════════════════════════════════════════════════

    def get_summary(self, correlation_run_id: str) -> CorrelationSummary:
        cr = self.get_correlation_run(correlation_run_id)

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
        active_attempt_id = cr.active_attempt_id

        # 单连接合并：采集质量 / 请求总数 / 可关联请求数 / 端点证据 / 触达统计 /
        # Finding 统计 / Attempt 完整性，全部在同一个只读连接内完成，避免此前
        # 两段 ro_conn + 独立 eligible COUNT 的三次连接与多次表扫描往返。
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
                total_row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM http_request_evidence WHERE blackbox_run_id = ?",
                    (bb_id,),
                ).fetchone()
                summary.captured_request_count = total_row["cnt"] if total_row else 0

            # ── 可关联请求（只 COUNT 合格请求，不物化行）──
            eligible_row = conn.execute(
                """SELECT COUNT(*) AS cnt FROM http_request_evidence
                   WHERE blackbox_run_id = ?
                     AND endpoint_match_eligibility IN ('CONFIRMED_ELIGIBLE', 'ATTEMPT_ONLY')""",
                (bb_id,),
            ).fetchone()
            summary.correlatable_request_count = eligible_row["cnt"] if eligible_row else 0

            if active_attempt_id is None:
                return summary

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
                (active_attempt_id,),
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
                (active_attempt_id,),
            ).fetchone()
            summary.confirmed_touched_endpoint_count = (
                confirmed_touch["cnt"] if confirmed_touch else 0
            )

            candidate_touch = conn.execute(
                """SELECT COUNT(DISTINCT eec.endpoint_id) AS cnt
                   FROM endpoint_evidence_candidates eec
                   JOIN endpoint_evidence ee ON ee.endpoint_evidence_id = eec.endpoint_evidence_id
                   WHERE ee.correlation_attempt_id = ?""",
                (active_attempt_id,),
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
            # 三桶互斥切分：confirmed + candidate + unrelated == total。
            fe_stats = conn.execute(
                """SELECT best_relation_type,
                          COUNT(*) AS cnt,
                          SUM(CASE WHEN confirmed_request_count > 0 THEN 1 ELSE 0 END) AS confirmed_cnt,
                          SUM(CASE WHEN confirmed_request_count = 0
                                    AND candidate_request_count > 0 THEN 1 ELSE 0 END) AS candidate_cnt
                   FROM finding_evidence
                   WHERE correlation_attempt_id = ?
                   GROUP BY best_relation_type""",
                (active_attempt_id,),
            ).fetchall()
            for row in fe_stats:
                cnt = row["cnt"] or 0
                confirmed_cnt = row["confirmed_cnt"] or 0
                candidate_cnt = row["candidate_cnt"] or 0
                summary.total_finding_count += cnt
                summary.confirmed_related_finding_count += confirmed_cnt
                summary.candidate_related_finding_count += candidate_cnt
                summary.unrelated_finding_count += cnt - confirmed_cnt - candidate_cnt

            # Attempt 完整性
            attempt = conn.execute(
                "SELECT evidence_completeness FROM correlation_attempts WHERE correlation_attempt_id = ?",
                (active_attempt_id,),
            ).fetchone()
            if attempt:
                summary.evidence_completeness = attempt["evidence_completeness"]

        return summary

    # ══════════════════════════════════════════════════════════
    # 崩溃恢复
    # ══════════════════════════════════════════════════════════

    def recover_stale_attempts(self) -> list[CorrelationAttempt]:
        """将 lease 过期的 RUNNING Attempt 标记为 ABORTED，并回退 Run 状态。

        批量处理（替代逐 attempt 三次查询/事务）：一次 UPDATE 批量 ABORT，
        再一次 UPDATE 回退受影响的 Run 状态（仅 RUNNING，按是否已绑定分析区分
        READY / WAITING_ANALYSIS）。
        """
        stale = self.list_running_attempts_with_expired_lease()
        if not stale:
            return []

        attempt_ids = [a.correlation_attempt_id for a in stale]
        placeholders = ",".join("?" for _ in attempt_ids)
        now = _utc_now_iso()
        with self._pool.tx() as conn:
            conn.execute(
                f"UPDATE correlation_attempts SET status = 'ABORTED', completed_at = ? "
                f"WHERE correlation_attempt_id IN ({placeholders})",
                (now, *attempt_ids),
            )

        # 回退 Run 状态并清除 active_attempt_id / completed_at：claim 不再设置
        # active_attempt_id，完成时才原子发布，因此恢复时必须清除旧的
        # active_attempt_id 避免指向 ABORTED attempt；同时清除 completed_at，
        # 避免 READY 状态下残留旧完成时间戳。
        run_ids = sorted({a.correlation_run_id for a in stale})
        run_placeholders = ",".join("?" for _ in run_ids)
        with self._pool.tx() as conn:
            conn.execute(
                f"""UPDATE correlation_runs
                    SET status = CASE WHEN analysis_id IS NOT NULL THEN 'READY'
                                      ELSE 'WAITING_ANALYSIS' END,
                        active_attempt_id = NULL,
                        completed_at = NULL
                    WHERE correlation_run_id IN ({run_placeholders})
                      AND status = 'RUNNING'""",
                run_ids,
            )
        return stale
