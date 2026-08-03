"""analysis_runs 及结构化投影表读写。"""

from __future__ import annotations

import base64
import json
from typing import Any

from argus_py.analysis.enums import (
    AnalysisRunStatus,
)
from argus_py.analysis.models import AnalysisRun, QualityIssue
from argus_py.infra.db import DbPool

# ── 行映射 ──────────────────────────────────────────────────────────


def _analysis_run_to_row(run: AnalysisRun) -> tuple:
    return (
        run.analysis_id,
        run.task_id,
        run.source_snapshot_id,
        run.resolved_commit_sha,
        run.run_status,
        run.completeness_status,
        run.external_job_id,
        run.external_job_status,
        run.failure_code,
        run.failure_message,
        run.stop_reason,
        run.result_schema_version,
        run.result_digest,
        run.config_json,
        run.raw_result_json,
        run.quality_policy_version,
        json.dumps([qi.to_dict() for qi in run.quality_issues], ensure_ascii=False),
        run.started_at,
        run.completed_at,
        run.projection_completed_at,
        run.created_at or _utc_now(),
        run.updated_at or _utc_now(),
    )


def _row_to_analysis_run(row: dict[str, Any]) -> AnalysisRun:
    quality_issues_raw = row.get("quality_issues_json") or "[]"
    quality_issues = [QualityIssue.from_dict(qi) for qi in json.loads(quality_issues_raw)]
    return AnalysisRun(
        analysis_id=row["analysis_id"],
        task_id=row["task_id"],
        source_snapshot_id=row["source_snapshot_id"],
        resolved_commit_sha=row.get("resolved_commit_sha"),
        run_status=row["run_status"],
        completeness_status=row["completeness_status"],
        external_job_id=row.get("external_job_id"),
        external_job_status=row.get("external_job_status"),
        failure_code=row.get("failure_code"),
        failure_message=row.get("failure_message"),
        stop_reason=row.get("stop_reason"),
        result_schema_version=row.get("result_schema_version", 1),
        result_digest=row.get("result_digest"),
        config_json=row.get("config_json"),
        raw_result_json=row.get("raw_result_json"),
        quality_policy_version=row.get("quality_policy_version", 1),
        quality_issues=quality_issues,
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        projection_completed_at=row.get("projection_completed_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


# ── 投影行映射 ────────────────────────────────────────────────────────


def _endpoint_to_row(aid: str, ep: dict[str, Any]) -> tuple:
    return (
        ep["endpoint_id"],
        aid,
        ep["endpoint_fingerprint"],
        ep["http_method"],
        ep["raw_path"],
        ep.get("normalized_exact_path"),
        ep["normalized_path_template"],
        int(ep.get("is_templated", False)),
        ep.get("path_normalization_version", 1),
        ep.get("path_segment_count", 0),
        ep.get("static_prefix"),
        ep.get("canonical_path_shape"),
        ep.get("controller_class"),
        ep.get("controller_method"),
        ep.get("controller_method_signature"),
        json.dumps(ep.get("parameters", []), ensure_ascii=False),
        ep.get("return_type"),
        ep.get("source_file"),
        ep.get("source_start_line"),
        ep.get("source_start_column"),
        ep.get("source_end_line"),
        ep.get("source_end_column"),
        ep.get("entry_call_node_id"),
    )


def _row_to_endpoint(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "endpoint_id": row["endpoint_id"],
        "endpoint_fingerprint": row["endpoint_fingerprint"],
        "http_method": row["http_method"],
        "raw_path": row["raw_path"],
        "normalized_exact_path": row.get("normalized_exact_path"),
        "normalized_path_template": row["normalized_path_template"],
        "is_templated": bool(row.get("is_templated", False)),
        "path_normalization_version": row.get("path_normalization_version", 1),
        "path_segment_count": row.get("path_segment_count", 0),
        "static_prefix": row.get("static_prefix"),
        "canonical_path_shape": row.get("canonical_path_shape"),
        "controller_class": row.get("controller_class"),
        "controller_method": row.get("controller_method"),
        "controller_method_signature": row.get("controller_method_signature"),
        "parameters": json.loads(row.get("parameters") or "[]"),
        "return_type": row.get("return_type"),
        "source_file": row.get("source_file"),
        "source_start_line": row.get("source_start_line"),
        "source_start_column": row.get("source_start_column"),
        "source_end_line": row.get("source_end_line"),
        "source_end_column": row.get("source_end_column"),
        "entry_call_node_id": row.get("entry_call_node_id"),
    }


def _call_node_to_row(aid: str, cn: dict[str, Any]) -> tuple:
    return (
        cn["call_node_id"],
        aid,
        cn["call_node_fingerprint"],
        cn["class_name"],
        cn["method_name"],
        cn.get("method_signature"),
        cn.get("source_file"),
        cn.get("source_start_line"),
        cn.get("source_start_column"),
        cn.get("source_end_line"),
        cn.get("source_end_column"),
    )


def _row_to_call_node(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_node_id": row["call_node_id"],
        "call_node_fingerprint": row["call_node_fingerprint"],
        "class_name": row["class_name"],
        "method_name": row["method_name"],
        "method_signature": row.get("method_signature"),
        "source_file": row.get("source_file"),
        "source_start_line": row.get("source_start_line"),
        "source_start_column": row.get("source_start_column"),
        "source_end_line": row.get("source_end_line"),
        "source_end_column": row.get("source_end_column"),
    }


def _call_edge_to_row(aid: str, ce: dict[str, Any]) -> tuple:
    return (
        ce["call_edge_id"],
        aid,
        ce["from_node_id"],
        ce["to_node_id"],
        ce.get("to_class_name"),
        ce.get("to_method_name"),
        ce.get("resolution_type"),
        ce.get("confidence"),
        ce.get("source_file"),
        ce.get("source_start_line"),
        ce.get("source_start_column"),
        ce.get("source_end_line"),
        ce.get("source_end_column"),
    )


def _row_to_call_edge(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_edge_id": row["call_edge_id"],
        "from_node_id": row["from_node_id"],
        "to_node_id": row["to_node_id"],
        "to_class_name": row.get("to_class_name"),
        "to_method_name": row.get("to_method_name"),
        "resolution_type": row.get("resolution_type"),
        "confidence": row.get("confidence"),
        "source_file": row.get("source_file"),
        "source_start_line": row.get("source_start_line"),
        "source_start_column": row.get("source_start_column"),
        "source_end_line": row.get("source_end_line"),
        "source_end_column": row.get("source_end_column"),
    }


def _flow_to_row(aid: str, flow: dict[str, Any]) -> tuple:
    return (
        flow["execution_flow_id"],
        aid,
        flow.get("execution_flow_fingerprint", ""),
        flow["entry_point"],
        flow.get("call_depth", 0),
    )


def _row_to_flow(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_flow_id": row["execution_flow_id"],
        "execution_flow_fingerprint": row.get("execution_flow_fingerprint", ""),
        "entry_point": row["entry_point"],
        "call_depth": row.get("call_depth", 0),
    }


def _flow_step_to_row(fid: str, step: dict[str, Any]) -> tuple:
    return (
        step["flow_step_id"],
        fid,
        step["step_index"],
        step.get("depth", 0),
        step["method_key"],
        step.get("class_name"),
        step.get("method_name"),
        step.get("call_node_id"),
    )


def _row_to_flow_step(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "flow_step_id": row["flow_step_id"],
        "execution_flow_id": row["execution_flow_id"],
        "step_index": row["step_index"],
        "depth": row.get("depth", 0),
        "method_key": row.get("method_key"),
        "class_name": row.get("class_name"),
        "method_name": row.get("method_name"),
        "call_node_id": row.get("call_node_id"),
    }


# ── 聚类行映射 ──


def _cluster_to_row(aid: str, cluster: dict[str, Any]) -> tuple:
    return (
        cluster["cluster_id"],
        aid,
        cluster.get("suggested_label", ""),
        json.dumps(cluster.get("member_keys", []), ensure_ascii=False),
        cluster.get("member_count", 0),
    )


def _row_to_cluster(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cluster_id": row["cluster_id"],
        "analysis_id": row["analysis_id"],
        "suggested_label": row.get("suggested_label", ""),
        "member_keys": json.loads(row.get("member_keys_json") or "[]"),
        "member_count": row.get("member_count", 0),
    }


# ── Repository ────────────────────────────────────────────────────────


class AnalysisRunRepository:
    """analysis_runs 及结构化投影表读写。"""

    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    # ── 分析执行 CRUD ──────────────────────────────────────────────

    def create(self, run: AnalysisRun) -> AnalysisRun:
        with self._pool.tx() as conn:
            conn.execute(
                """INSERT INTO analysis_runs (
                    analysis_id, task_id, source_snapshot_id, resolved_commit_sha,
                    run_status, completeness_status, external_job_id, external_job_status,
                    failure_code, failure_message, stop_reason,
                    result_schema_version, result_digest,
                    config_json, raw_result_json,
                    quality_policy_version, quality_issues_json,
                    started_at, completed_at, projection_completed_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _analysis_run_to_row(run),
            )
        return run

    def get(self, analysis_id: str) -> AnalysisRun | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_runs WHERE analysis_id = ?", (analysis_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_analysis_run(row)

    def list_by_task(
        self,
        task_id: str,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AnalysisRun], int]:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM analysis_runs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            total = row["cnt"] if row else 0
            rows = conn.execute(
                "SELECT * FROM analysis_runs WHERE task_id = ? "
                "ORDER BY created_at DESC, analysis_id DESC "
                "LIMIT ? OFFSET ?",
                (task_id, limit, offset),
            ).fetchall()
        return [_row_to_analysis_run(r) for r in rows], total

    def get_latest(self, task_id: str) -> AnalysisRun | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_runs WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_analysis_run(row)

    def get_latest_succeeded_by_project(
        self,
        project_id: str,
        *,
        source_snapshot_id: str | None = None,
    ) -> AnalysisRun | None:
        """查找同一项目下最新成功的分析执行（JOIN tasks.project_id）。

        若提供 source_snapshot_id，仅返回 resolved_commit_sha 一致的分析；
        否则返回同项目最新成功分析（不限制快照）。
        """
        with self._pool.ro_conn() as conn:
            conditions = ["t.project_id = ?", "ar.run_status = 'SUCCEEDED'"]
            params: list[Any] = [project_id]
            if source_snapshot_id:
                conditions.append("ar.resolved_commit_sha = ?")
                params.append(source_snapshot_id)
            query = (
                "SELECT ar.* FROM analysis_runs ar "
                "INNER JOIN tasks t ON t.task_id = ar.task_id "
                "WHERE " + " AND ".join(conditions) + " "
                "ORDER BY ar.created_at DESC LIMIT 1"
            )
            row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        return _row_to_analysis_run(dict(row))

    def update_status(
        self,
        analysis_id: str,
        run_status: str,
        **kw: Any,
    ) -> None:
        """原子更新 run_status + 可选字段，自动维护 updated_at。"""
        sets = ["run_status = ?"]
        values: list[Any] = [run_status]
        for col in (
            "completeness_status",
            "external_job_id",
            "external_job_status",
            "failure_code",
            "failure_message",
            "stop_reason",
            "result_digest",
            "raw_result_json",
            "quality_issues_json",
            "started_at",
            "completed_at",
            "projection_completed_at",
        ):
            if col in kw:
                sets.append(f"{col} = ?")
                values.append(kw[col])
        sets.append("updated_at = datetime('now')")
        values.append(analysis_id)
        with self._pool.tx() as conn:
            conn.execute(
                f"UPDATE analysis_runs SET {', '.join(sets)} WHERE analysis_id = ?",
                values,
            )

    def save_raw_result(self, analysis_id: str, raw_json: str, digest: str) -> None:
        """事务 1：独立保存原始结果 + digest。"""
        with self._pool.tx() as conn:
            conn.execute(
                "UPDATE analysis_runs SET raw_result_json = ?, result_digest = ?, "
                "updated_at = datetime('now') WHERE analysis_id = ?",
                (raw_json, digest, analysis_id),
            )

    def mark_failed(
        self,
        analysis_id: str,
        failure_code: str,
        failure_message: str,
    ) -> None:
        """事务 3：投影失败标记。"""
        self.update_status(
            analysis_id,
            run_status=AnalysisRunStatus.FAILED.value,
            failure_code=failure_code,
            failure_message=failure_message,
        )

    def complete_projection(
        self,
        analysis_id: str,
        *,
        completeness: str,
        quality_issues_json: str,
        result_digest: str,
        projection_data: dict[str, Any],
    ) -> None:
        """事务 2：重建全部投影 + 标记 SUCCEEDED + 完整性结论，同一事务。

        全部成功提交后才对外可见；投影失败则整体回滚。
        ``projection_data`` 预期包含 key:
          endpoints, call_nodes, call_edges, execution_flows, flow_steps, diagnostics
        """
        with self._pool.tx() as conn:
            self._write_projection(conn, analysis_id, projection_data)
            conn.execute(
                "UPDATE analysis_runs SET run_status = ?, completeness_status = ?, "
                "quality_issues_json = ?, result_digest = ?, "
                "projection_completed_at = ?, updated_at = datetime('now') "
                "WHERE analysis_id = ?",
                (
                    AnalysisRunStatus.SUCCEEDED.value,
                    completeness,
                    quality_issues_json,
                    result_digest,
                    _utc_now(),
                    analysis_id,
                ),
            )

    def _write_projection(
        self, conn: Any, analysis_id: str, projection_data: dict[str, Any]
    ) -> None:
        """在已有事务中写入全部结构化投影（内部辅助，不自行管理事务）。"""
        # 幂等清理旧投影（按外键依赖顺序：子表 → 父表）
        conn.execute(
            "DELETE FROM analysis_flow_steps WHERE execution_flow_id IN "
            "(SELECT execution_flow_id FROM analysis_execution_flows WHERE analysis_id = ?)",
            (analysis_id,),
        )
        conn.execute(
            "DELETE FROM analysis_execution_flows WHERE analysis_id = ?",
            (analysis_id,),
        )
        conn.execute(
            "DELETE FROM analysis_call_edges WHERE analysis_id = ?",
            (analysis_id,),
        )
        conn.execute(
            "DELETE FROM analysis_endpoints WHERE analysis_id = ?",
            (analysis_id,),
        )
        conn.execute(
            "DELETE FROM analysis_call_nodes WHERE analysis_id = ?",
            (analysis_id,),
        )
        conn.execute(
            "DELETE FROM analysis_diagnostics WHERE analysis_id = ?",
            (analysis_id,),
        )
        conn.execute(
            "DELETE FROM analysis_clusters WHERE analysis_id = ?",
            (analysis_id,),
        )

        # 写入 CallNode（先写，因为后续外键引用）
        for cn in projection_data.get("call_nodes", []):
            conn.execute(
                """INSERT INTO analysis_call_nodes (
                    call_node_id, analysis_id, call_node_fingerprint,
                    class_name, method_name, method_signature,
                    source_file, source_start_line, source_start_column,
                    source_end_line, source_end_column
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _call_node_to_row(analysis_id, cn),
            )

        # Endpoint
        for ep in projection_data.get("endpoints", []):
            conn.execute(
                """INSERT INTO analysis_endpoints (
                    endpoint_id, analysis_id, endpoint_fingerprint,
                    http_method, raw_path, normalized_exact_path,
                    normalized_path_template, is_templated,
                    path_normalization_version, path_segment_count,
                    static_prefix, canonical_path_shape,
                    controller_class, controller_method,
                    controller_method_signature,
                    parameters, return_type,
                    source_file, source_start_line, source_start_column,
                    source_end_line, source_end_column,
                    entry_call_node_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _endpoint_to_row(analysis_id, ep),
            )

        # CallEdge
        for ce in projection_data.get("call_edges", []):
            conn.execute(
                """INSERT INTO analysis_call_edges (
                    call_edge_id, analysis_id, from_node_id, to_node_id,
                    to_class_name, to_method_name,
                    resolution_type, confidence,
                    source_file, source_start_line, source_start_column,
                    source_end_line, source_end_column
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _call_edge_to_row(analysis_id, ce),
            )

        # ExecutionFlow
        for flow in projection_data.get("execution_flows", []):
            conn.execute(
                """INSERT INTO analysis_execution_flows (
                    execution_flow_id, analysis_id, execution_flow_fingerprint,
                    entry_point, call_depth
                ) VALUES (?, ?, ?, ?, ?)""",
                _flow_to_row(analysis_id, flow),
            )

        # FlowStep
        for step in projection_data.get("flow_steps", []):
            conn.execute(
                """INSERT INTO analysis_flow_steps (
                    flow_step_id, execution_flow_id, step_index, depth,
                    method_key, class_name, method_name, call_node_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                _flow_step_to_row(step.get("execution_flow_id", ""), step),
            )

        # Diagnostics
        diag = projection_data.get("diagnostics")
        if diag:
            conn.execute(
                """INSERT INTO analysis_diagnostics (
                    analysis_id, total_source_files, eligible_source_files,
                    parsed_file_count, failed_file_count, failed_files,
                    total_calls, resolved_high, resolved_medium,
                    resolved_low, unresolved,
                    classpath_available, jar_count, classpath_source,
                    classpath_warnings, classpath_errors,
                    module_count, application_module_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    analysis_id,
                    diag.get("total_source_files", 0),
                    diag.get("eligible_source_files", 0),
                    diag.get("parsed_file_count", 0),
                    diag.get("failed_file_count", 0),
                    json.dumps(diag.get("failed_files", []), ensure_ascii=False),
                    diag.get("total_calls", 0),
                    diag.get("resolved_high", 0),
                    diag.get("resolved_medium", 0),
                    diag.get("resolved_low", 0),
                    diag.get("unresolved", 0),
                    int(diag.get("classpath_available", False)),
                    diag.get("jar_count", 0),
                    diag.get("classpath_source"),
                    json.dumps(diag.get("classpath_warnings", []), ensure_ascii=False),
                    json.dumps(diag.get("classpath_errors", []), ensure_ascii=False),
                    diag.get("module_count", 0),
                    diag.get("application_module_count", 0),
                ),
            )

        # Clusters
        for cluster in projection_data.get("clusters", []):
            conn.execute(
                """INSERT INTO analysis_clusters (
                    cluster_id, analysis_id, suggested_label,
                    member_keys_json, member_count
                ) VALUES (?, ?, ?, ?, ?)""",
                _cluster_to_row(analysis_id, cluster),
            )

    # ── 分页查询 ──────────────────────────────────────────────────

    def list_endpoints(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._paginated_query(
            "analysis_endpoints",
            analysis_id,
            order="normalized_path_template ASC, http_method ASC, endpoint_id ASC",
            cursor=cursor,
            limit=limit,
        )

    def list_call_nodes(
        self,
        analysis_id: str,
        *,
        class_name: str | None = None,
        method_name: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        where = "analysis_id = ?"
        params: list[Any] = [analysis_id]
        if class_name:
            where += " AND class_name LIKE ?"
            params.append(f"%{class_name}%")
        if method_name:
            where += " AND method_name LIKE ?"
            params.append(f"%{method_name}%")
        return self._paginated_query(
            "analysis_call_nodes",
            params=params,
            where_clause=where,
            order="class_name ASC, method_name ASC, call_node_id ASC",
            cursor=cursor,
            limit=limit,
        )

    def list_call_edges(
        self,
        analysis_id: str,
        *,
        entry_node_id: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        if entry_node_id:
            where = "analysis_id = ? AND from_node_id = ?"
            params: list[Any] = [analysis_id, entry_node_id]
        else:
            where = "analysis_id = ?"
            params = [analysis_id]
        return self._paginated_query(
            "analysis_call_edges",
            params=params,
            where_clause=where,
            order="call_edge_id ASC",
            cursor=cursor,
            limit=limit,
        )

    def list_execution_flows(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._paginated_query(
            "analysis_execution_flows",
            analysis_id,
            order="entry_point ASC, execution_flow_id ASC",
            cursor=cursor,
            limit=limit,
        )

    def get_flow_steps(self, flow_id: str) -> list[dict[str, Any]]:
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM analysis_flow_steps WHERE execution_flow_id = ? "
                "ORDER BY step_index ASC",
                (flow_id,),
            ).fetchall()
        return [_row_to_flow_step(r) for r in rows]

    def list_all_flow_steps_by_analysis(self, analysis_id: str) -> list[dict[str, Any]]:
        """一次查询获取分析的所有 flow steps（JOIN execution_flows），避免 N+1。"""
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                """SELECT afs.* FROM analysis_flow_steps afs
                   JOIN analysis_execution_flows aef
                     ON aef.execution_flow_id = afs.execution_flow_id
                   WHERE aef.analysis_id = ?
                   ORDER BY afs.execution_flow_id, afs.step_index""",
                (analysis_id,),
            ).fetchall()
        return [_row_to_flow_step(r) for r in rows]

    def get_diagnostics(self, analysis_id: str) -> dict[str, Any] | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_diagnostics WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "analysis_id": row["analysis_id"],
            "total_source_files": row["total_source_files"],
            "eligible_source_files": row["eligible_source_files"],
            "parsed_file_count": row["parsed_file_count"],
            "failed_file_count": row["failed_file_count"],
            "failed_files": json.loads(row.get("failed_files") or "[]"),
            "total_calls": row["total_calls"],
            "resolved_high": row["resolved_high"],
            "resolved_medium": row["resolved_medium"],
            "resolved_low": row["resolved_low"],
            "unresolved": row["unresolved"],
            "classpath_available": bool(row["classpath_available"]),
            "jar_count": row["jar_count"],
            "classpath_source": row["classpath_source"],
            "classpath_warnings": json.loads(row.get("classpath_warnings") or "[]"),
            "classpath_errors": json.loads(row.get("classpath_errors") or "[]"),
            "module_count": row["module_count"],
            "application_module_count": row["application_module_count"],
        }

    def list_clusters(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        """分页查询聚类。"""
        return self._paginated_query(
            "analysis_clusters",
            analysis_id,
            order="suggested_label ASC, cluster_id ASC",
            cursor=cursor,
            limit=limit,
        )

    def get_counts(self, analysis_id: str) -> dict[str, int]:
        """返回各投影表的记录数（含 findings 表按 analysis_id 过滤）。"""
        counts: dict[str, int] = {}
        with self._pool.ro_conn() as conn:
            for table in (
                "analysis_endpoints",
                "analysis_call_nodes",
                "analysis_call_edges",
                "analysis_execution_flows",
                "analysis_clusters",
            ):
                row = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM {table} WHERE analysis_id = ?",
                    (analysis_id,),
                ).fetchone()
                counts[table] = row["cnt"] if row else 0
            # findings 表示在 findings 表中而非 analysis_ 前缀
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM findings WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
            counts["findings"] = row["cnt"] if row else 0
        return counts

    def get_finding_severity_counts(self, analysis_id: str) -> dict[str, int]:
        """返回 findings 按严重级别的分布（如 {"CRITICAL": 1, "HIGH": 3}）。"""
        counts: dict[str, int] = {}
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT severity, COUNT(*) AS cnt FROM findings "
                "WHERE analysis_id = ? GROUP BY severity",
                (analysis_id,),
            ).fetchall()
        for row in rows:
            sev = row["severity"]
            if isinstance(sev, str) and sev:
                counts[sev] = row["cnt"]
        return counts

    # ── 内部辅助 ──────────────────────────────────────────────────

    def _paginated_query(
        self,
        table: str,
        params: Any = None,
        *,
        where_clause: str | None = None,
        order: str = "",
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        if isinstance(params, str):
            where_clause = "analysis_id = ?"
            params = [params]
        elif where_clause is None:
            raise ValueError("Must provide either analysis_id or where_clause")

        sql = f"SELECT * FROM {table} WHERE {where_clause}"
        with self._pool.ro_conn() as conn:
            # total（仅在首屏请求时计算）
            row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM {table} WHERE {where_clause}",
                params,
            ).fetchone()
            total: int | None = row["cnt"] if row else 0

            limit = min(limit, 200)
            if cursor:
                # 游标编码：base64(json({"k": [sort_key_values]}))
                try:
                    decoded = json.loads(base64.urlsafe_b64decode(cursor).decode())
                    cursor_keys = decoded["k"]
                    # 游标过滤：排序键 > 游标值
                    # 简化实现：按 order 提取列名构造 WHERE 子句
                    order_cols = [c.strip().split()[0] for c in order.split(",")]
                    cursor_conds = []
                    cursor_params = list(params)
                    for i, col in enumerate(order_cols):
                        prefix_cols = [c.strip().split()[0] for c in order.split(",")[:i]]
                        prefix_cond = (
                            " AND ".join(f"{pc} = ?" for pc in prefix_cols) if prefix_cols else ""
                        )
                        if prefix_cond:
                            cursor_conds.append(f"({prefix_cond} AND {col} > ?)")
                            for j, _pc in enumerate(prefix_cols[:i]):
                                cursor_params.append(cursor_keys[j])
                            cursor_params.append(cursor_keys[i])
                        else:
                            cursor_conds.append(f"{col} > ?")
                            cursor_params.append(cursor_keys[i])
                    sql += f" AND ({' OR '.join(cursor_conds)})"
                    params = cursor_params
                except Exception:
                    cursor = None  # 游标无效，从头开始

            sql += f" ORDER BY {order} LIMIT ?"
            params_with_limit = list(params) + [limit + 1]
            rows = conn.execute(sql, params_with_limit).fetchall()

        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = None
        if has_more and items:
            # 游标编码最后一行的排序键
            order_cols = [c.strip().split()[0] for c in order.split(",")]
            last = items[-1]
            cursor_payload = {"k": [last[col] for col in order_cols]}
            next_cursor = base64.urlsafe_b64encode(json.dumps(cursor_payload).encode()).decode()
        return items, next_cursor, total, has_more


def _utc_now() -> str:
    from argus_py.core.constants import utc_now as _now

    return _now().isoformat()
