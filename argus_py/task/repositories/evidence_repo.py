"""请求/端点/Finding 证据表读写（http_request_evidence、endpoint_evidence 及关系表）。"""

from __future__ import annotations

from typing import Any

from argus_py.correlation.models import (
    EndpointEvidence,
    EndpointEvidenceCandidate,
    EndpointEvidenceFlow,
    FindingEvidence,
    FindingEvidenceLink,
    HttpRequestEvidence,
)
from argus_py.infra.db import DbPool
from argus_py.task.repositories.mappers import (
    endpoint_evidence_to_row,
    http_request_to_row,
    row_to_http_request,
)

# SQLite 默认编译期参数上限 999，留安全余量
_BATCH_QUERY_MAX_IDS = 900


def _check_batch_ids(ids: list[str], label: str) -> None:
    if len(ids) > _BATCH_QUERY_MAX_IDS:
        raise ValueError(f"{label} 批量查询 ID 数量超出限制: {len(ids)} > {_BATCH_QUERY_MAX_IDS}")


class EvidenceRepository:
    """证据侧聚合：请求证据、端点证据及其候选/调用流/Finding 关联。"""

    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    def _load_run_refs(self, correlation_run_id: str) -> tuple[str | None, str | None]:
        """轻量读取关联运行的 (blackbox_run_id, active_attempt_id)。"""
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT blackbox_run_id, active_attempt_id FROM correlation_runs "
                "WHERE correlation_run_id = ?",
                (correlation_run_id,),
            ).fetchone()
        if row is None:
            return None, None
        return row["blackbox_run_id"], row["active_attempt_id"]

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
                [http_request_to_row(item) for item in items],
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
        return [row_to_http_request(dict(r)) for r in rows], total

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
        return [row_to_http_request(dict(r)) for r in rows]

    def list_unmatched_requests(
        self,
        correlation_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[HttpRequestEvidence], int]:
        """获取 resolution_status='UNMATCHED' 的请求（通过 endpoint_evidence 状态过滤）。

        只统计 active_attempt 的证据，避免重试/重算后混入旧 Attempt 的记录。
        """
        bb_id, attempt_id = self._load_run_refs(correlation_run_id)
        if bb_id is None or attempt_id is None:
            return [], 0
        with self._pool.ro_conn() as conn:
            total_row = conn.execute(
                """SELECT COUNT(*) AS cnt FROM http_request_evidence hre
                   INNER JOIN endpoint_evidence ee ON ee.request_evidence_id = hre.request_evidence_id
                     AND ee.correlation_attempt_id = ?
                   WHERE hre.blackbox_run_id = ? AND ee.resolution_status = 'UNMATCHED'""",
                (attempt_id, bb_id),
            ).fetchone()
            total = total_row["cnt"] if total_row else 0
            rows = conn.execute(
                """SELECT hre.* FROM http_request_evidence hre
                   INNER JOIN endpoint_evidence ee ON ee.request_evidence_id = hre.request_evidence_id
                     AND ee.correlation_attempt_id = ?
                   WHERE hre.blackbox_run_id = ? AND ee.resolution_status = 'UNMATCHED'
                   ORDER BY hre.request_sequence LIMIT ? OFFSET ?""",
                (attempt_id, bb_id, limit, offset),
            ).fetchall()
        return [row_to_http_request(dict(r)) for r in rows], total

    def list_all_unmatched_requests(self, correlation_run_id: str) -> list[HttpRequestEvidence]:
        """返回全部 UNMATCHED 请求（无分页钳制，关联报告聚合用）。

        过滤语义与 ``list_unmatched_requests`` 一致（仅统计 active_attempt 的
        证据），但不截断，避免报告明细被固定 limit 静默裁剪。
        """
        bb_id, attempt_id = self._load_run_refs(correlation_run_id)
        if bb_id is None or attempt_id is None:
            return []
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                """SELECT hre.* FROM http_request_evidence hre
                   INNER JOIN endpoint_evidence ee ON ee.request_evidence_id = hre.request_evidence_id
                     AND ee.correlation_attempt_id = ?
                   WHERE hre.blackbox_run_id = ? AND ee.resolution_status = 'UNMATCHED'
                   ORDER BY hre.request_sequence""",
                (attempt_id, bb_id),
            ).fetchall()
        return [row_to_http_request(dict(r)) for r in rows]

    # ══════════════════════════════════════════════════════════
    # EndpointEvidence + 关系表
    # ══════════════════════════════════════════════════════════

    def insert_evidence_batch(self, items: list[EndpointEvidence]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT INTO endpoint_evidence (
                    endpoint_evidence_id, correlation_run_id, correlation_attempt_id,
                    request_evidence_id, resolution_status, match_strategy, confidence,
                    matched_endpoint_id, matcher_version,
                    normalization_version, candidate_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [endpoint_evidence_to_row(item) for item in items],
            )

    def insert_candidates_batch(self, items: list[EndpointEvidenceCandidate]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO endpoint_evidence_candidates (
                    endpoint_evidence_id, endpoint_id, candidate_rank,
                    match_strategy, confidence, selected
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        c.endpoint_evidence_id,
                        c.endpoint_id,
                        c.candidate_rank,
                        c.match_strategy.value,
                        c.confidence.value,
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

    def list_confirmed_touched_endpoints(self, attempt_id: str) -> list[dict[str, Any]]:
        """按端点分组的确认触达证据（UNIQUE + EXACT/TEMPLATE，排除 ATTEMPT_ONLY）。

        返回 rows: {endpoint_id, http_method, confirmed_request_count, evidence_ids}
        evidence_ids 为逗号分隔的 endpoint_evidence_id 列表（报告重生成聚合调用流用）。
        """
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                """SELECT ee.matched_endpoint_id AS endpoint_id,
                          hre.http_method,
                          COUNT(*) AS confirmed_request_count,
                          GROUP_CONCAT(ee.endpoint_evidence_id) AS evidence_ids
                   FROM endpoint_evidence ee
                   JOIN http_request_evidence hre
                     ON hre.request_evidence_id = ee.request_evidence_id
                   WHERE ee.correlation_attempt_id = ?
                     AND ee.resolution_status = 'UNIQUE'
                     AND ee.match_strategy IN ('EXACT', 'TEMPLATE')
                     AND ee.matched_endpoint_id IS NOT NULL
                     AND hre.endpoint_match_eligibility != 'ATTEMPT_ONLY'
                   GROUP BY ee.matched_endpoint_id, hre.http_method""",
                (attempt_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_uncovered_endpoints(
        self,
        correlation_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        """获取未被确认触达的端点（无 UNIQUE+EXACT/TEMPLATE 证据）。"""
        with self._pool.ro_conn() as conn:
            cr_row = conn.execute(
                "SELECT analysis_id, active_attempt_id FROM correlation_runs "
                "WHERE correlation_run_id = ?",
                (correlation_run_id,),
            ).fetchone()
            if (
                cr_row is None
                or cr_row["analysis_id"] is None
                or cr_row["active_attempt_id"] is None
            ):
                return [], 0
            analysis_id = cr_row["analysis_id"]
            attempt_id = cr_row["active_attempt_id"]

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
                (analysis_id, attempt_id),
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
                (analysis_id, attempt_id, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows], total

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
        _, attempt_id = self._load_run_refs(correlation_run_id)
        if attempt_id is None:
            return [], 0
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

    def list_all_finding_evidence(self, correlation_run_id: str) -> list[dict[str, Any]]:
        """返回全部 Finding 关联证据行（无分页钳制，关联报告聚合用）。"""
        _, attempt_id = self._load_run_refs(correlation_run_id)
        if attempt_id is None:
            return []
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM finding_evidence WHERE correlation_attempt_id = ? "
                "ORDER BY confirmed_request_count DESC",
                (attempt_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════
    # Attempt 明细表
    # ══════════════════════════════════════════════════════════

    def insert_attempt_reasons_batch(self, items: list[Any]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO correlation_attempt_reasons (
                    correlation_attempt_id, reason_code, detail
                ) VALUES (?, ?, ?)""",
                [(r.correlation_attempt_id, r.reason_code.value, r.detail) for r in items],
            )

    def insert_attempt_diagnostics_batch(self, items: list[Any]) -> None:
        with self._pool.tx() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO correlation_attempt_diagnostics (
                    correlation_attempt_id, diagnostic_code, detail
                ) VALUES (?, ?, ?)""",
                [(d.correlation_attempt_id, d.diagnostic_code.value, d.detail) for d in items],
            )

    # ══════════════════════════════════════════════════════════
    # 批量查询辅助（供 application 层组装 API 响应）
    # ══════════════════════════════════════════════════════════

    def batch_get_candidates(self, evidence_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """按 evidence_id 批量查询候选端点。"""
        if not evidence_ids:
            return {}
        _check_batch_ids(evidence_ids, "candidates")
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
        """按 evidence_id 批量查询调用流关联，返回完整 ExecutionFlowResponse 结构。

        经 execution_flow_id 关联 analysis_execution_flows + analysis_flow_steps
        组装完整执行流（键与 ExecutionFlowResponse 的 camelCase alias 对齐）；
        对 analysis 侧已清理的孤儿 flow_id 直接跳过，避免产生残缺条目。
        """
        if not evidence_ids:
            return {}
        _check_batch_ids(evidence_ids, "flows")
        with self._pool.ro_conn() as conn:
            ev_placeholders = ",".join("?" for _ in evidence_ids)
            links = conn.execute(
                f"SELECT endpoint_evidence_id, execution_flow_id "
                f"FROM endpoint_evidence_flows "
                f"WHERE endpoint_evidence_id IN ({ev_placeholders})",
                evidence_ids,
            ).fetchall()
            if not links:
                return {}

            # flow_ids 的数量不受 evidence_ids 上限约束（一条证据可关联多条流），
            # 分片查询以避免单个 IN 子句超过 SQLite 变量数上限。
            flows: dict[str, dict[str, Any]] = {}
            steps_by_flow: dict[str, list[dict[str, Any]]] = {}
            flow_ids = sorted({r["execution_flow_id"] for r in links})
            for start in range(0, len(flow_ids), _BATCH_QUERY_MAX_IDS):
                chunk = flow_ids[start : start + _BATCH_QUERY_MAX_IDS]
                placeholders = ",".join("?" for _ in chunk)
                for row in conn.execute(
                    f"SELECT * FROM analysis_execution_flows "
                    f"WHERE execution_flow_id IN ({placeholders})",
                    chunk,
                ).fetchall():
                    flows[row["execution_flow_id"]] = dict(row)
                for row in conn.execute(
                    f"SELECT * FROM analysis_flow_steps "
                    f"WHERE execution_flow_id IN ({placeholders}) "
                    f"ORDER BY execution_flow_id, step_index",
                    chunk,
                ).fetchall():
                    steps_by_flow.setdefault(row["execution_flow_id"], []).append(dict(row))

        result: dict[str, list[dict[str, Any]]] = {}
        for link in links:
            eid = link["endpoint_evidence_id"]
            flow = flows.get(link["execution_flow_id"])
            if flow is None:
                continue  # 孤儿引用：analysis 侧执行流已清理，跳过
            result.setdefault(eid, []).append(
                {
                    "executionFlowId": flow["execution_flow_id"],
                    "entryPoint": flow["entry_point"],
                    "callDepth": flow["call_depth"],
                    "steps": [
                        {
                            "flowStepId": s["flow_step_id"],
                            "stepIndex": s["step_index"],
                            "depth": s["depth"],
                            "methodKey": s["method_key"],
                            "className": s["class_name"],
                            "methodName": s["method_name"],
                            "callNodeId": s["call_node_id"],
                        }
                        for s in steps_by_flow.get(link["execution_flow_id"], [])
                    ],
                }
            )
        return result

    def batch_get_endpoint_details(self, endpoint_ids: list[str]) -> dict[str, dict[str, Any]]:
        """按 endpoint_id 批量查询端点详情。"""
        if not endpoint_ids:
            return {}
        _check_batch_ids(endpoint_ids, "endpoint_details")
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
        _check_batch_ids(finding_ids, "finding_details")
        with self._pool.ro_conn() as conn:
            placeholders = ",".join("?" for _ in finding_ids)
            rows = conn.execute(
                f"SELECT * FROM findings WHERE finding_id IN ({placeholders})",
                finding_ids,
            ).fetchall()
        return {r["finding_id"]: dict(r) for r in rows}
