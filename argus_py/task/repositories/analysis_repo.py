"""analysis_runs 及结构化投影表读写。"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from itertools import islice
from typing import Any

from argus_py.analysis.enums import (
    AnalysisRunStatus,
)
from argus_py.analysis.models import AnalysisRun, QualityIssue
from argus_py.infra.db import DbPool

# mark_terminal 仅允许的非失败终态（取消/超时）；真实失败一律走 mark_failed。
# SUCCEEDED 必须由 complete_projection 事务写入（同时构建投影与完整性结论），
# 不允许经 mark_terminal 直接置位，否则会出现"无投影的 SUCCEEDED"。
_MARK_TERMINAL_ALLOWED: frozenset[AnalysisRunStatus] = frozenset(
    {
        AnalysisRunStatus.STOPPED_WAITING,
        AnalysisRunStatus.CANCELLED,
        AnalysisRunStatus.TIMED_OUT,
    }
)

# 投影写入单批行数。executemany 会一次性持有整批行元组，批过大会在
# 超大批次时瞬时翻倍内存；批过小则退化为接近逐行 execute。基准建议
# 200～1000，这里取中间值 500。
_PROJECTION_BATCH_SIZE = 500


def _executemany_batched(
    conn: Any,
    sql: str,
    rows: Iterable[tuple],
    *,
    batch_size: int = _PROJECTION_BATCH_SIZE,
) -> None:
    """在同一事务内分批 ``executemany``，控制单批内存上限。

    接受任意可迭代对象（列表或生成器）：逐批 ``islice`` 取出
    ``batch_size`` 行后调用 ``executemany``。行源为生成器时，峰值内存
    只保留当前批，不随总行数增长。事务边界由调用方
    （``complete_projection`` 的 ``tx()``）保证：任一批失败都会回滚
    整个投影，不会暴露半份写入。
    """
    it = iter(rows)
    while True:
        chunk = list(islice(it, batch_size))
        if not chunk:
            break
        conn.executemany(sql, chunk)


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
    # sqlite3.Row 没有 .get()，统一转 dict 后再读取
    if not isinstance(row, dict):
        row = dict(row)
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
    # 兼容 sqlite3.Row（无 .get()）和 dict
    keys = row.keys()

    def _g(k: str, default: Any = None) -> Any:
        return row[k] if k in keys else default

    return {
        "flow_step_id": _g("flow_step_id"),
        "execution_flow_id": _g("execution_flow_id"),
        "step_index": _g("step_index"),
        "depth": _g("depth", 0),
        "method_key": _g("method_key"),
        "class_name": _g("class_name"),
        "method_name": _g("method_name"),
        "call_node_id": _g("call_node_id"),
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

    def mark_terminal(
        self,
        analysis_id: str,
        run_status: AnalysisRunStatus,
        failure_code: str,
        failure_message: str,
    ) -> None:
        """将 analysis_runs 置为指定终态，保留失败代码/消息供诊断。

        仅接受取消（STOPPED_WAITING / CANCELLED）与超时（TIMED_OUT）等
        非失败终态；失败路径仍走 :meth:`mark_failed`，SUCCEEDED 必须由
        :meth:`complete_projection` 事务写入。
        """
        if run_status not in _MARK_TERMINAL_ALLOWED:
            allowed = sorted(s.value for s in _MARK_TERMINAL_ALLOWED)
            raise ValueError(f"mark_terminal 仅接受非失败终态 {allowed}，收到: {run_status}")
        self.update_status(
            analysis_id,
            run_status=run_status.value,
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

        # 行源构造为生成器，在同一事务内分批 executemany，把 Python↔SQLite
        # 的往返从逐行 execute 降为每批一次；峰值内存只保留当前批，不随
        # 总行数增长（_executemany_batched 内部 islice 分片）。
        # CallNode 先写（后续外键引用）。
        _executemany_batched(
            conn,
            """INSERT INTO analysis_call_nodes (
                call_node_id, analysis_id, call_node_fingerprint,
                class_name, method_name, method_signature,
                source_file, source_start_line, source_start_column,
                source_end_line, source_end_column
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_call_node_to_row(analysis_id, cn) for cn in projection_data.get("call_nodes", [])),
        )

        # Endpoint
        _executemany_batched(
            conn,
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
            (_endpoint_to_row(analysis_id, ep) for ep in projection_data.get("endpoints", [])),
        )

        # CallEdge
        _executemany_batched(
            conn,
            """INSERT INTO analysis_call_edges (
                call_edge_id, analysis_id, from_node_id, to_node_id,
                to_class_name, to_method_name,
                resolution_type, confidence,
                source_file, source_start_line, source_start_column,
                source_end_line, source_end_column
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_call_edge_to_row(analysis_id, ce) for ce in projection_data.get("call_edges", [])),
        )

        # ExecutionFlow
        _executemany_batched(
            conn,
            """INSERT INTO analysis_execution_flows (
                execution_flow_id, analysis_id, execution_flow_fingerprint,
                entry_point, call_depth
            ) VALUES (?, ?, ?, ?, ?)""",
            (
                _flow_to_row(analysis_id, flow)
                for flow in projection_data.get("execution_flows", [])
            ),
        )

        # FlowStep
        _executemany_batched(
            conn,
            """INSERT INTO analysis_flow_steps (
                flow_step_id, execution_flow_id, step_index, depth,
                method_key, class_name, method_name, call_node_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _flow_step_to_row(step.get("execution_flow_id", ""), step)
                for step in projection_data.get("flow_steps", [])
            ),
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
        _executemany_batched(
            conn,
            """INSERT INTO analysis_clusters (
                cluster_id, analysis_id, suggested_label,
                member_keys_json, member_count
            ) VALUES (?, ?, ?, ?, ?)""",
            (
                _cluster_to_row(analysis_id, cluster)
                for cluster in projection_data.get("clusters", [])
            ),
        )

    # ── 分页查询 ──────────────────────────────────────────────────

    def list_endpoints(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        items, next_cursor, total, has_more = self._paginated_query(
            "analysis_endpoints",
            analysis_id,
            order="normalized_path_template ASC, http_method ASC, endpoint_id ASC",
            cursor=cursor,
            limit=limit,
        )
        return [_row_to_endpoint(r) for r in items], next_cursor, total, has_more

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
        items, next_cursor, total, has_more = self._paginated_query(
            "analysis_call_nodes",
            params=params,
            where_clause=where,
            order="class_name ASC, method_name ASC, call_node_id ASC",
            cursor=cursor,
            limit=limit,
        )
        return (
            [_row_to_call_node(r) for r in items],
            next_cursor,
            total,
            has_more,
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
        items, next_cursor, total, has_more = self._paginated_query(
            "analysis_call_edges",
            params=params,
            where_clause=where,
            order="call_edge_id ASC",
            cursor=cursor,
            limit=limit,
        )
        return (
            [_row_to_call_edge(r) for r in items],
            next_cursor,
            total,
            has_more,
        )

    def list_execution_flows(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        items, next_cursor, total, has_more = self._paginated_query(
            "analysis_execution_flows",
            analysis_id,
            order="entry_point ASC, execution_flow_id ASC",
            cursor=cursor,
            limit=limit,
        )
        return [_row_to_flow(r) for r in items], next_cursor, total, has_more

    # ── 非分页"取全部"查询（关联匹配引擎专用）─────────────────────────
    #
    # 分页查询 `_paginated_query` 将 limit 钳制在 200（前端分页语义），但关联
    # 匹配引擎需要投影全量行（端点/调用节点/执行流/发现）才能生成完整证据。
    # 此前引擎传 10_000/50_000 期望加载全部却被静默截断为前 200 行，导致
    # 关联证据与未触达列表只覆盖前 200 行。以下方法直接全量查询、不做
    # 分页钳制，也不执行 COUNT。

    def list_all_endpoints(self, analysis_id: str) -> list[dict[str, Any]]:
        """返回分析的全部端点（无 200 行钳制，关联匹配用）。"""
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM analysis_endpoints WHERE analysis_id = ? "
                "ORDER BY normalized_path_template ASC, http_method ASC, endpoint_id ASC",
                (analysis_id,),
            ).fetchall()
        return [_row_to_endpoint(dict(r)) for r in rows]

    def list_all_call_nodes(self, analysis_id: str) -> list[dict[str, Any]]:
        """返回分析的全部调用节点（无 200 行钳制，关联匹配用）。"""
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM analysis_call_nodes WHERE analysis_id = ? "
                "ORDER BY class_name ASC, method_name ASC, call_node_id ASC",
                (analysis_id,),
            ).fetchall()
        return [_row_to_call_node(dict(r)) for r in rows]

    def list_all_execution_flows(self, analysis_id: str) -> list[dict[str, Any]]:
        """返回分析的全部执行流（无 200 行钳制，关联匹配用）。"""
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM analysis_execution_flows WHERE analysis_id = ? "
                "ORDER BY entry_point ASC, execution_flow_id ASC",
                (analysis_id,),
            ).fetchall()
        return [_row_to_flow(dict(r)) for r in rows]

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
        row = dict(row)  # sqlite3.Row 无 .get()，统一转 dict
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
        items, next_cursor, total, has_more = self._paginated_query(
            "analysis_clusters",
            analysis_id,
            order="suggested_label ASC, cluster_id ASC",
            cursor=cursor,
            limit=limit,
        )
        return [_row_to_cluster(r) for r in items], next_cursor, total, has_more

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

    def get_counts_batch(self, analysis_ids: list[str]) -> dict[str, dict[str, int]]:
        """批量返回多个分析的投影计数（analysis_id → 各表 COUNT）。

        ``GET /tasks/{id}/analysis-runs`` 列表对每个 run 串行执行 6+1 条 COUNT，
        N 个 run 最坏 N×7 条 SQL。此处用 ``IN (...) GROUP BY analysis_id``
        一次批量取回，消除 N+1 COUNT。
        """
        if not analysis_ids:
            return {}
        placeholders = ",".join("?" for _ in analysis_ids)
        # 与 get_counts 一致：为每个 analysis_id 预置全部表键（无行时为 0），
        # 保证批量结果与逐条 get_counts 结构等价。
        result: dict[str, dict[str, int]] = {
            aid: {
                t: 0
                for t in (
                    "analysis_endpoints",
                    "analysis_call_nodes",
                    "analysis_call_edges",
                    "analysis_execution_flows",
                    "analysis_clusters",
                )
            }
            | {"findings": 0}
            for aid in analysis_ids
        }
        with self._pool.ro_conn() as conn:
            for table in (
                "analysis_endpoints",
                "analysis_call_nodes",
                "analysis_call_edges",
                "analysis_execution_flows",
                "analysis_clusters",
            ):
                rows = conn.execute(
                    f"SELECT analysis_id, COUNT(*) AS cnt FROM {table} "
                    f"WHERE analysis_id IN ({placeholders}) GROUP BY analysis_id",
                    analysis_ids,
                ).fetchall()
                for row in rows:
                    result[row["analysis_id"]][table] = row["cnt"]
            # findings 表示在 findings 表中而非 analysis_ 前缀
            rows = conn.execute(
                f"SELECT analysis_id, COUNT(*) AS cnt FROM findings "
                f"WHERE analysis_id IN ({placeholders}) GROUP BY analysis_id",
                analysis_ids,
            ).fetchall()
            for row in rows:
                result[row["analysis_id"]]["findings"] = row["cnt"]
        return result

    def get_finding_severity_counts_batch(
        self, analysis_ids: list[str]
    ) -> dict[str, dict[str, int]]:
        """批量返回多个分析的 findings 严重级别分布（analysis_id → severity → count）。"""
        if not analysis_ids:
            return {}
        placeholders = ",".join("?" for _ in analysis_ids)
        result: dict[str, dict[str, int]] = {}
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                f"SELECT analysis_id, severity, COUNT(*) AS cnt FROM findings "
                f"WHERE analysis_id IN ({placeholders}) GROUP BY analysis_id, severity",
                analysis_ids,
            ).fetchall()
        for row in rows:
            sev = row["severity"]
            if isinstance(sev, str) and sev:
                result.setdefault(row["analysis_id"], {})[sev] = row["cnt"]
        return result

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

        # 游标编码：base64(json({"k": [sort_key_values]}))。解码或校验失败
        # （非列表 / 键数与排序列不符）时回退为首页请求：仍计算 total。
        order_cols = [c.strip().split()[0] for c in order.split(",")]
        cursor_keys: list[Any] | None = None
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor).decode())
                keys = decoded["k"]
                if not isinstance(keys, list) or len(keys) != len(order_cols):
                    raise ValueError("cursor keys must match order columns")
                # 键元素必须为标量（str/int/float，显式排除 bool/None/容器），否则
                # 长度合规但元素非标量的游标会在 SQLite 参数绑定时抛 500，而不是回退首页。
                if any(not isinstance(k, (str, int, float)) or isinstance(k, bool) for k in keys):
                    raise ValueError("cursor keys must be scalar")
                cursor_keys = keys
            except Exception:
                cursor = None
                cursor_keys = None

        sql = f"SELECT * FROM {table} WHERE {where_clause}"
        with self._pool.ro_conn() as conn:
            # total 仅在首屏请求（无有效 cursor）时计算；后续 cursor 页返回
            # None，由客户端复用首屏 total，避免每页执行全表/索引 COUNT。
            total: int | None = None
            if cursor is None:
                row = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM {table} WHERE {where_clause}",
                    params,
                ).fetchone()
                total = row["cnt"] if row else 0

            limit = min(limit, 200)
            if cursor_keys is not None:
                # 游标过滤：排序键 > 游标值
                # 简化实现：按 order 提取列名构造 WHERE 子句
                cursor_conds = []
                cursor_params = list(params)
                for i, col in enumerate(order_cols):
                    prefix_cols = order_cols[:i]
                    prefix_cond = (
                        " AND ".join(f"{pc} = ?" for pc in prefix_cols) if prefix_cols else ""
                    )
                    if prefix_cond:
                        cursor_conds.append(f"({prefix_cond} AND {col} > ?)")
                        cursor_params.extend(cursor_keys[:i])
                        cursor_params.append(cursor_keys[i])
                    else:
                        cursor_conds.append(f"{col} > ?")
                        cursor_params.append(cursor_keys[i])
                sql += f" AND ({' OR '.join(cursor_conds)})"
                params = cursor_params

            sql += f" ORDER BY {order} LIMIT ?"
            params_with_limit = list(params) + [limit + 1]
            rows = conn.execute(sql, params_with_limit).fetchall()

        has_more = len(rows) > limit
        items = [dict(r) for r in rows[:limit]]
        next_cursor = None
        if has_more and items:
            # 游标编码最后一行的排序键
            last = items[-1]
            cursor_payload = {"k": [last[col] for col in order_cols]}
            next_cursor = base64.urlsafe_b64encode(json.dumps(cursor_payload).encode()).decode()
        return items, next_cursor, total, has_more


def _utc_now() -> str:
    from argus_py.core.constants import utc_now as _now

    return _now().isoformat()
