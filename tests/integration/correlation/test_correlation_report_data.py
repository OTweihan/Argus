"""阶段四：白盒报告关联数据构建 — build_correlation_report_data 聚合正确性。

覆盖：跨运行触达并集、ATTEMPT_ONLY 排除、调用流组装、未覆盖端点、未匹配请求仅 displayPath、
finding 关联去重、无关联运行返回 None，以及新查询 list_confirmed_touched_endpoints 的 SQL 形状。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.correlation.enums import (
    MatchConfidence,
    MatchStrategy,
    ResolutionStatus,
)
from argus_py.correlation.models import EndpointEvidence, EndpointEvidenceFlow
from argus_py.task.application import build_correlation_report_data
from argus_py.task.models import Task
from argus_py.task.storage import TaskSQLiteStorage

from tests.integration.correlation._fixtures import setup_base_tables

pytestmark = [pytest.mark.integration]


def _seed_correlation_report_data(storage: TaskSQLiteStorage, db: Path) -> None:
    """写入白盒分析 + 关联运行 + 证据（含 ATTEMPT_ONLY / AMBIGUOUS / UNMATCHED）。"""
    task = Task(
        task_id="t-rep",
        goal="report data",
        project_id="p1",
        task_type=TaskType.WHITEBOX,
        status=TaskStatus.COMPLETED,
    )
    storage.save(task)

    from argus_py.analysis.models import AnalysisRun

    ar = AnalysisRun(
        analysis_id="an-rep",
        task_id="t-rep",
        source_snapshot_id="src-rep",
        resolved_commit_sha="abc123",
        run_status="SUCCEEDED",
        config_json="{}",
    )
    storage.create_analysis_run(ar)

    # 3 个端点：ep-1（会被确认触达）、ep-2（ATTEMPT_ONLY）、ep-3（未触达）
    eps = [
        {
            "endpoint_id": "ep-1",
            "http_method": "GET",
            "raw_path": "/api/users",
            "normalized_exact_path": "/api/users",
            "normalized_path_template": "/api/users",
            "is_templated": 0,
            "path_normalization_version": "v1",
            "path_segment_count": 2,
            "static_prefix": "/api/users",
            "canonical_path_shape": "/api/users",
            "controller_class": "UserController",
            "controller_method": "listUsers",
            "controller_method_signature": "List<User> listUsers()",
            "parameters": "",
            "return_type": "List<User>",
            "source_file": "com/example/UserController.java",
            "source_start_line": 42,
            "source_start_column": 5,
            "source_end_line": 55,
            "source_end_column": 1,
            "entry_call_node_id": "cn-1",
        },
        {
            "endpoint_id": "ep-2",
            "http_method": "POST",
            "raw_path": "/api/orders",
            "normalized_exact_path": "/api/orders",
            "normalized_path_template": "/api/orders",
            "is_templated": 0,
            "path_normalization_version": "v1",
            "path_segment_count": 2,
            "static_prefix": "/api/orders",
            "canonical_path_shape": "/api/orders",
            "controller_class": "OrderController",
            "controller_method": "createOrder",
            "controller_method_signature": "Order createOrder(OrderDto dto)",
            "parameters": "dto:OrderDto",
            "return_type": "Order",
            "source_file": "com/example/OrderController.java",
            "source_start_line": 80,
            "source_start_column": 5,
            "source_end_line": 100,
            "source_end_column": 1,
            "entry_call_node_id": "cn-2",
        },
        {
            "endpoint_id": "ep-3",
            "http_method": "DELETE",
            "raw_path": "/api/cache",
            "normalized_exact_path": "/api/cache",
            "normalized_path_template": "/api/cache",
            "is_templated": 0,
            "path_normalization_version": "v1",
            "path_segment_count": 2,
            "static_prefix": "/api/cache",
            "canonical_path_shape": "/api/cache",
            "controller_class": "CacheController",
            "controller_method": "clear",
            "controller_method_signature": "void clear()",
            "parameters": "",
            "return_type": "void",
            "source_file": "com/example/CacheController.java",
            "source_start_line": 10,
            "source_start_column": 5,
            "source_end_line": 12,
            "source_end_column": 1,
            "entry_call_node_id": "cn-3",
        },
    ]
    from argus_py.task.repositories.analysis_repo import _endpoint_to_row

    with storage._analysis._pool.tx() as conn:
        for ep in eps:
            ep.setdefault("endpoint_fingerprint", f"fp:{ep['endpoint_id']}")
            conn.execute(
                """INSERT OR IGNORE INTO analysis_endpoints (
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
                _endpoint_to_row("an-rep", ep),
            )

    # 执行流 + steps
    with storage._analysis._pool.tx() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO analysis_execution_flows (
                execution_flow_id, analysis_id, execution_flow_fingerprint,
                entry_point, call_depth
            ) VALUES (?, ?, ?, ?, ?)""",
            ("flow-1", "an-rep", "fp:flow-1", "UserController.listUsers", 1),
        )
        conn.execute(
            """INSERT OR IGNORE INTO analysis_flow_steps (
                flow_step_id, execution_flow_id, step_index, depth,
                method_key, class_name, method_name, call_node_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "fs-1",
                "flow-1",
                0,
                0,
                "UserController.listUsers",
                "UserController",
                "listUsers",
                "cn-1",
            ),
        )
        conn.execute(
            """INSERT OR IGNORE INTO analysis_flow_steps (
                flow_step_id, execution_flow_id, step_index, depth,
                method_key, class_name, method_name, call_node_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("fs-2", "flow-1", 1, 1, "UserService.find", "UserService", "find", "cn-4"),
        )

    # finding 记录（供 finding_evidence 关联详情查询）
    with storage._tasks._pool.tx() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO findings (
                finding_id, task_id, analysis_id, title, description,
                severity, finding_type, location, url,
                rule_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "f-rep",
                "t-rep",
                "an-rep",
                "空 catch",
                "描述",
                "high",
                "functional",
                "com/example/UserController.java:45",
                "",
                "SQLI-001",
                "2024-01-01",
            ),
        )

    # 关联运行（绑定 an-rep）+ attempt（active）
    with storage._correlation._pool.tx() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO correlation_runs (
                correlation_run_id, project_id, blackbox_run_id,
                desired_source_snapshot_id, correlation_config_digest,
                matcher_version, normalization_version,
                analysis_id, bound_source_snapshot_id, analysis_projection_version,
                status, created_at
            ) VALUES (?, 'p1', ?, 'abc123', 'd1', 'v1', 'v1', ?, 'abc123', 1, 'READY', '2024-01-01')""",
            ("cr-rep", "bb1", "an-rep"),
        )
        conn.execute(
            """INSERT OR IGNORE INTO correlation_attempts (
                correlation_attempt_id, correlation_run_id, attempt_number,
                analysis_id, source_snapshot_id, analysis_projection_version,
                matcher_version, normalization_version, correlation_config_digest,
                status, evidence_completeness,
                started_at, created_at
            ) VALUES (?, ?, 1, 'an-rep', 'abc123', 1, 'v1', 'v1', 'd1', 'SUCCEEDED', 'COMPLETE',
                      '2024-01-01', '2024-01-01')""",
            ("ca-rep", "cr-rep"),
        )
        conn.execute(
            "UPDATE correlation_runs SET active_attempt_id = ? WHERE correlation_run_id = ?",
            ("ca-rep", "cr-rep"),
        )

    # 请求证据
    requests = [
        # (rid, method, path, eligibility)
        ("req-confirmed", "GET", "/api/users", "CONFIRMED_ELIGIBLE"),
        ("req-ambiguous", "GET", "/api/orders", "CONFIRMED_ELIGIBLE"),
        ("req-attempt-only", "POST", "/api/orders", "ATTEMPT_ONLY"),
        ("req-unmatched", "GET", "/api/unknown", "CONFIRMED_ELIGIBLE"),
    ]
    with storage._correlation._pool.tx() as conn:
        for seq, (rid, method, path, eligibility) in enumerate(requests, start=1):
            conn.execute(
                """INSERT OR IGNORE INTO http_request_evidence (
                    request_evidence_id, blackbox_run_id, task_id, step_execution_id,
                    request_sequence, http_method, normalized_path, display_path, origin,
                    endpoint_match_eligibility, outcome, request_owner, captured_at
                ) VALUES (?, 'bb1', 't1', NULL, ?, ?, ?, ?, 'https://example.com',
                          ?, 'COMPLETED', 'FRAME', '2024-01-01')""",
                (rid, seq, method, path, path, eligibility),
            )

    # 端点证据
    evidences = [
        # 确认触达 ep-1（EXACT）
        EndpointEvidence(
            endpoint_evidence_id="eev-1",
            correlation_run_id="cr-rep",
            correlation_attempt_id="ca-rep",
            request_evidence_id="req-confirmed",
            resolution_status=ResolutionStatus.UNIQUE,
            match_strategy=MatchStrategy.EXACT,
            confidence=MatchConfidence.HIGH,
            matched_endpoint_id="ep-1",
            candidate_count=1,
            created_at="2024-01-01",
        ),
        # 歧义：matched_endpoint_id 必须为 None
        EndpointEvidence(
            endpoint_evidence_id="eev-2",
            correlation_run_id="cr-rep",
            correlation_attempt_id="ca-rep",
            request_evidence_id="req-ambiguous",
            resolution_status=ResolutionStatus.AMBIGUOUS,
            match_strategy=MatchStrategy.TEMPLATE,
            confidence=MatchConfidence.MEDIUM,
            matched_endpoint_id=None,
            candidate_count=2,
            created_at="2024-01-01",
        ),
        # ATTEMPT_ONLY：UNIQUE 但不计入确认触达
        EndpointEvidence(
            endpoint_evidence_id="eev-3",
            correlation_run_id="cr-rep",
            correlation_attempt_id="ca-rep",
            request_evidence_id="req-attempt-only",
            resolution_status=ResolutionStatus.UNIQUE,
            match_strategy=MatchStrategy.EXACT,
            confidence=MatchConfidence.HIGH,
            matched_endpoint_id="ep-2",
            candidate_count=1,
            created_at="2024-01-01",
        ),
        # UNMATCHED
        EndpointEvidence(
            endpoint_evidence_id="eev-4",
            correlation_run_id="cr-rep",
            correlation_attempt_id="ca-rep",
            request_evidence_id="req-unmatched",
            resolution_status=ResolutionStatus.UNMATCHED,
            match_strategy=MatchStrategy.NONE,
            confidence=MatchConfidence.UNKNOWN,
            matched_endpoint_id=None,
            candidate_count=0,
            created_at="2024-01-01",
        ),
    ]
    storage.insert_endpoint_evidence_batch(evidences)

    # 调用流关联：eev-1 → flow-1
    storage.insert_flows_batch(
        [
            EndpointEvidenceFlow(
                endpoint_evidence_id="eev-1",
                execution_flow_id="flow-1",
                relation_type="STATIC_REACHABLE",
                flow_name_snapshot="UserController.listUsers",
                endpoint_path_snapshot="/api/users",
                controller_snapshot="UserController",
            )
        ]
    )

    # finding 关联
    with storage._correlation._pool.tx() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO finding_evidence (
                finding_evidence_id, correlation_attempt_id, finding_id,
                best_relation_type, minimum_call_distance,
                confirmed_request_count, candidate_request_count,
                finding_rule_id_snapshot, finding_location_snapshot
            ) VALUES (?, 'ca-rep', 'f-rep', 'DIRECT_HANDLER', 0, 2, 0, 'SQLI-001',
                      'com/example/UserController.java:45')""",
            ("fe-rep",),
        )


class TestListConfirmedTouchedEndpoints:
    def test_sql_shape_excludes_attempt_only(self, tmp_path: Path) -> None:
        storage = setup_base_tables(tmp_path / "t.db")
        _seed_correlation_report_data(storage, tmp_path)

        rows = storage.list_confirmed_touched_endpoints("ca-rep")

        assert len(rows) == 1
        row = rows[0]
        assert row["endpoint_id"] == "ep-1"
        assert row["http_method"] == "GET"
        assert row["confirmed_request_count"] == 1
        assert "eev-1" in row["evidence_ids"]


class TestBuildCorrelationReportData:
    def test_aggregate_union_and_attempt_only_excluded(self, tmp_path: Path) -> None:
        storage = setup_base_tables(tmp_path / "t.db")
        _seed_correlation_report_data(storage, tmp_path)

        data = build_correlation_report_data(storage, "an-rep")

        assert data is not None
        agg = data["aggregate"]
        # ep-1 确认触达；ep-2 是 ATTEMPT_ONLY 不计入；ep-3 未触达
        assert agg["confirmedTouchedEndpointCount"] == 1
        assert agg["totalEndpointCount"] == 3
        assert agg["uncoveredEndpointCount"] == 2
        assert agg["runCount"] == 1
        assert agg["evidenceCompleteness"] == "COMPLETE"
        # 匹配请求：eev-1(UNIQUE) + eev-2(AMBIGUOUS) 计入 correlatable；UNMATCHED 单独
        assert agg["confirmedMatchedRequestCount"] == 1
        assert agg["ambiguousRequestCount"] == 1
        assert agg["unmatchedRequestCount"] == 1

    def test_touched_endpoints_carry_flows(self, tmp_path: Path) -> None:
        storage = setup_base_tables(tmp_path / "t.db")
        _seed_correlation_report_data(storage, tmp_path)

        data = build_correlation_report_data(storage, "an-rep")
        assert data is not None
        touched = data["touchedEndpoints"]

        assert len(touched) == 1
        ep = touched[0]
        assert ep["endpointId"] == "ep-1"
        assert ep["httpMethod"] == "GET"
        assert ep["path"] == "/api/users"
        assert ep["confirmedRequestCount"] == 1
        assert ep["runIds"] == ["cr-rep"]
        assert len(ep["flows"]) == 1
        flow = ep["flows"][0]
        assert flow["executionFlowId"] == "flow-1"
        assert flow["entryPoint"] == "UserController.listUsers"
        assert flow["callDepth"] == 1
        assert len(flow["steps"]) == 2
        assert flow["steps"][0]["methodName"] == "listUsers"
        # snake_case 键不得泄漏
        assert "evidenceIds" not in ep

    def test_uncovered_endpoints_exclude_touched(self, tmp_path: Path) -> None:
        storage = setup_base_tables(tmp_path / "t.db")
        _seed_correlation_report_data(storage, tmp_path)

        data = build_correlation_report_data(storage, "an-rep")
        assert data is not None
        uncovered_ids = {ep["endpointId"] for ep in data["uncoveredEndpoints"]}

        assert uncovered_ids == {"ep-2", "ep-3"}

    def test_unmatched_requests_only_display_path(self, tmp_path: Path) -> None:
        storage = setup_base_tables(tmp_path / "t.db")
        _seed_correlation_report_data(storage, tmp_path)

        data = build_correlation_report_data(storage, "an-rep")
        assert data is not None
        unmatched = data["unmatchedRequests"]

        assert len(unmatched) == 1
        req = unmatched[0]
        assert req["httpMethod"] == "GET"
        assert req["displayPath"] == "/api/unknown"
        # 不得携带 normalized_path / query
        assert "normalizedPath" not in req
        assert "requestPath" not in req

    def test_finding_relations_dedup(self, tmp_path: Path) -> None:
        storage = setup_base_tables(tmp_path / "t.db")
        _seed_correlation_report_data(storage, tmp_path)

        data = build_correlation_report_data(storage, "an-rep")
        assert data is not None
        relations = data["findingRelations"]

        assert len(relations) == 1
        fr = relations[0]
        assert fr["findingId"] == "f-rep"
        assert fr["title"] == "空 catch"
        assert fr["severity"] == "high"
        assert fr["ruleId"] == "SQLI-001"
        assert fr["bestRelationType"] == "DIRECT_HANDLER"
        assert fr["confirmedRequestCount"] == 2

    def test_none_when_no_correlation_runs(self, tmp_path: Path) -> None:
        storage = setup_base_tables(tmp_path / "t.db")
        # 未绑定任何关联运行的分析
        data = build_correlation_report_data(storage, "no-such-analysis")
        assert data is None
