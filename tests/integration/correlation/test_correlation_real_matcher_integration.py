"""阶段四：真实 Matcher 集成测试 — P1#5。

使用真实 DB 的 analysis_endpoints + http_request_evidence 表数据，
验证 EndpointMatcher.match_batch 在完整 Schema 数据下的精确匹配、
模板匹配、PATH_ONLY、double wildcard 和歧义候选生成。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.correlation.enums import (
    CorrelationEligibility,
    MatchConfidence,
    MatchStrategy,
    RequestOutcome,
    RequestOwner,
    ResolutionStatus,
)
from argus_py.correlation.matcher import EndpointMatcher
from argus_py.correlation.models import HttpRequestEvidence
from argus_py.task.models import Task
from argus_py.task.storage import TaskSQLiteStorage

from tests.integration.correlation._fixtures import setup_base_tables

pytestmark = [pytest.mark.integration]

# ── 工具函数 ──────────────────────────────────────────────────────


def _make_minimal_db(tmp_path: Path, analysis_id: str = "analysis-1") -> TaskSQLiteStorage:
    storage = setup_base_tables(tmp_path / "matcher.db")
    # 创建 analysis_run（FK 约束需要），也需要对应 task
    storage.save(
        Task(
            task_id=f"t-wb-{analysis_id}",
            goal="matcher test",
            project_id="p1",
            task_type=TaskType.WHITEBOX,
            status=TaskStatus.COMPLETED,
        )
    )
    from argus_py.analysis.models import AnalysisRun

    storage.create_analysis_run(
        AnalysisRun(
            analysis_id=analysis_id,
            task_id=f"t-wb-{analysis_id}",
            source_snapshot_id="src-1",
            resolved_commit_sha="abc123",
            run_status="SUCCEEDED",
            config_json="{}",
        )
    )
    return storage


def _insert_endpoints(storage: TaskSQLiteStorage, analysis_id: str, endpoints: list[dict]) -> None:
    """向 analysis_endpoints 批量写入端点数据。"""
    from argus_py.task.repositories.mappers import endpoint_to_row as _ep_row

    with storage._analysis._pool.tx() as conn:
        for ep in endpoints:
            ep.setdefault("endpoint_fingerprint", f"fp:{ep.get('endpoint_id', '?')}")
            ep.setdefault("path_normalization_version", "v1")
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
                _ep_row(analysis_id, ep),
            )


def _make_request(
    request_evidence_id: str,
    http_method: str,
    normalized_path: str,
    origin: str = "https://example.com",
    resource_type: str = "fetch",
) -> HttpRequestEvidence:
    return HttpRequestEvidence(
        request_evidence_id=request_evidence_id,
        blackbox_run_id="bb1",
        task_id="t1",
        step_execution_id=None,
        step_attempt=1,
        request_sequence=1,
        http_method=http_method,
        normalized_path=normalized_path,
        display_path=normalized_path,
        origin=origin,
        resource_type=resource_type,
        endpoint_match_eligibility=CorrelationEligibility.CONFIRMED_ELIGIBLE,
        outcome=RequestOutcome.COMPLETED,
        request_owner=RequestOwner.FRAME,
        captured_at="2024-01-01T00:00:00",
    )


def _insert_requests(storage: TaskSQLiteStorage, requests: list[HttpRequestEvidence]) -> None:
    storage.insert_http_request_batch(requests)


def _read_endpoints(storage: TaskSQLiteStorage, analysis_id: str) -> list[dict]:
    result = storage.list_analysis_endpoints(analysis_id, limit=1000)
    return result[0]


# ── 测试类 ────────────────────────────────────────────────────────


class TestRealMatcherIntegration:
    """EndpointMatcher 使用真实分析投影数据（完整 Schema 字段）的集成测试。"""

    def test_exact_match_with_real_endpoints(self, tmp_path: Path) -> None:
        """精确匹配：analysis_endpoints 真实写入 → Matcher 返回 UNIQUE EXACT。"""
        storage = _make_minimal_db(tmp_path)
        analysis_id = "analysis-1"

        eps = [
            {
                "endpoint_id": "ep-users",
                "http_method": "GET",
                "raw_path": "/api/users",
                "normalized_exact_path": "/api/users",
                "normalized_path_template": "",
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
                "entry_call_node_id": "cn-users",
            },
        ]
        _insert_endpoints(storage, analysis_id, eps)

        req = _make_request("req-1", "GET", "/api/users")
        matcher = EndpointMatcher()
        db_eps = _read_endpoints(storage, analysis_id)
        result = matcher.match_batch([req], db_eps)

        assert len(result.evidence_list) == 1
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.EXACT
        assert ev.matched_endpoint_id == "ep-users"
        assert ev.candidate_count == 1

    def test_template_match_with_real_db_data(self, tmp_path: Path) -> None:
        """模板匹配：{id} 参数化端点 → GET /api/users/42 匹配 UNIQUE。"""
        storage = _make_minimal_db(tmp_path)
        analysis_id = "analysis-1"

        eps = [
            {
                "endpoint_id": "ep-user-by-id",
                "http_method": "GET",
                "raw_path": "/api/users/{id}",
                "normalized_exact_path": "",
                "normalized_path_template": "/api/users/{id}",
                "is_templated": 1,
                "path_normalization_version": "v1",
                "path_segment_count": 3,
                "static_prefix": "/api/users",
                "canonical_path_shape": "/api/users/*",
                "controller_class": "UserController",
                "controller_method": "getUser",
                "controller_method_signature": "User getUser(Long id)",
                "parameters": "id:Long",
                "return_type": "User",
                "source_file": "com/example/UserController.java",
                "source_start_line": 60,
                "source_start_column": 5,
                "source_end_line": 72,
                "source_end_column": 1,
                "entry_call_node_id": "cn-user-by-id",
            },
        ]
        _insert_endpoints(storage, analysis_id, eps)

        req = _make_request("req-1", "GET", "/api/users/42")
        matcher = EndpointMatcher()
        db_eps = _read_endpoints(storage, analysis_id)
        result = matcher.match_batch([req], db_eps)

        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.TEMPLATE
        assert ev.matched_endpoint_id == "ep-user-by-id"

    def test_unmatched_with_real_db(self, tmp_path: Path) -> None:
        """无匹配端点 → UNMATCHED。"""
        storage = _make_minimal_db(tmp_path)
        analysis_id = "analysis-1"

        eps = [
            {
                "endpoint_id": "ep-get",
                "http_method": "GET",
                "raw_path": "/api/health",
                "normalized_exact_path": "/api/health",
                "normalized_path_template": "",
                "is_templated": 0,
                "path_normalization_version": "v1",
                "path_segment_count": 2,
                "static_prefix": "/api/health",
                "canonical_path_shape": "/api/health",
                "controller_class": "HealthController",
                "controller_method": "check",
                "controller_method_signature": "Health check()",
                "parameters": "",
                "return_type": "Health",
                "source_file": "com/example/HealthController.java",
                "source_start_line": 15,
                "source_start_column": 5,
                "source_end_line": 22,
                "source_end_column": 1,
                "entry_call_node_id": "cn-health",
            },
        ]
        _insert_endpoints(storage, analysis_id, eps)

        req = _make_request("req-1", "GET", "/api/nonexistent")
        matcher = EndpointMatcher()
        db_eps = _read_endpoints(storage, analysis_id)
        result = matcher.match_batch([req], db_eps)

        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNMATCHED
        assert ev.match_strategy == MatchStrategy.NONE
        assert ev.matched_endpoint_id is None

    def test_ambiguous_multiple_endpoints(self, tmp_path: Path) -> None:
        """同 (method, path) 的两个端点 → AMBIGUOUS + 候选生成。"""
        storage = _make_minimal_db(tmp_path)
        analysis_id = "analysis-1"

        eps = [
            {
                "endpoint_id": "ep-a",
                "http_method": "GET",
                "raw_path": "/api/users",
                "normalized_exact_path": "/api/users",
                "normalized_path_template": "",
                "is_templated": 0,
                "path_normalization_version": "v1",
                "path_segment_count": 2,
                "static_prefix": "/api/users",
                "canonical_path_shape": "/api/users",
                "controller_class": "UserControllerV1",
                "controller_method": "listUsers",
                "controller_method_signature": "List<User> listUsers()",
                "parameters": "",
                "return_type": "List<User>",
                "source_file": "com/example/v1/UserController.java",
                "source_start_line": 30,
                "source_start_column": 5,
                "source_end_line": 42,
                "source_end_column": 1,
                "entry_call_node_id": "cn-a",
            },
            {
                "endpoint_id": "ep-b",
                "http_method": "GET",
                "raw_path": "/api/users",
                "normalized_exact_path": "/api/users",
                "normalized_path_template": "",
                "is_templated": 0,
                "path_normalization_version": "v1",
                "path_segment_count": 2,
                "static_prefix": "/api/users",
                "canonical_path_shape": "/api/users",
                "controller_class": "UserControllerV2",
                "controller_method": "listUsers",
                "controller_method_signature": "List<UserDto> listUsers()",
                "parameters": "",
                "return_type": "List<UserDto>",
                "source_file": "com/example/v2/UserController.java",
                "source_start_line": 40,
                "source_start_column": 5,
                "source_end_line": 55,
                "source_end_column": 1,
                "entry_call_node_id": "cn-b",
            },
        ]
        _insert_endpoints(storage, analysis_id, eps)

        req = _make_request("req-1", "GET", "/api/users")
        matcher = EndpointMatcher()
        db_eps = _read_endpoints(storage, analysis_id)
        result = matcher.match_batch([req], db_eps)

        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.AMBIGUOUS
        assert ev.match_strategy == MatchStrategy.EXACT
        assert ev.candidate_count == 2
        assert ev.matched_endpoint_id is None
        assert len(result.candidates) == 2

    def test_path_only_real_db(self, tmp_path: Path) -> None:
        """方法不匹配但路径存在 → PATH_ONLY。"""
        storage = _make_minimal_db(tmp_path)
        analysis_id = "analysis-1"

        eps = [
            {
                "endpoint_id": "ep-get",
                "http_method": "GET",
                "raw_path": "/api/orders",
                "normalized_exact_path": "/api/orders",
                "normalized_path_template": "",
                "is_templated": 0,
                "path_normalization_version": "v1",
                "path_segment_count": 2,
                "static_prefix": "/api/orders",
                "canonical_path_shape": "/api/orders",
                "controller_class": "OrderController",
                "controller_method": "listOrders",
                "controller_method_signature": "List<Order> listOrders()",
                "parameters": "",
                "return_type": "List<Order>",
                "source_file": "com/example/OrderController.java",
                "source_start_line": 20,
                "source_start_column": 5,
                "source_end_line": 35,
                "source_end_column": 1,
                "entry_call_node_id": "cn-orders",
            },
        ]
        _insert_endpoints(storage, analysis_id, eps)

        req = _make_request("req-1", "POST", "/api/orders")
        matcher = EndpointMatcher()
        db_eps = _read_endpoints(storage, analysis_id)
        result = matcher.match_batch([req], db_eps)

        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.PATH_ONLY
        assert ev.confidence == MatchConfidence.LOW

    def test_double_wildcard_real_db(self, tmp_path: Path) -> None:
        """** 模板 → 匹配任意深度的路径。"""
        storage = _make_minimal_db(tmp_path)
        analysis_id = "analysis-1"

        eps = [
            {
                "endpoint_id": "ep-actuator",
                "http_method": "GET",
                "raw_path": "/actuator/**",
                "normalized_exact_path": "",
                "normalized_path_template": "/actuator/**",
                "is_templated": 1,
                "path_normalization_version": "v1",
                "path_segment_count": 1,
                "static_prefix": "/actuator",
                "canonical_path_shape": "/actuator/**",
                "controller_class": "ActuatorController",
                "controller_method": "handle",
                "controller_method_signature": "Object handle()",
                "parameters": "",
                "return_type": "Object",
                "source_file": "com/example/ActuatorController.java",
                "source_start_line": 10,
                "source_start_column": 5,
                "source_end_line": 18,
                "source_end_column": 1,
                "entry_call_node_id": "cn-act",
            },
        ]
        _insert_endpoints(storage, analysis_id, eps)

        req = _make_request("req-1", "GET", "/actuator/health/readiness")
        matcher = EndpointMatcher()
        db_eps = _read_endpoints(storage, analysis_id)
        result = matcher.match_batch([req], db_eps)

        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.TEMPLATE
        assert ev.matched_endpoint_id == "ep-actuator"

    def test_regex_param_real_db(self, tmp_path: Path) -> None:
        """{id:[0-9]+} 正则参数 → 数字匹配、字符串不匹配。"""
        storage = _make_minimal_db(tmp_path)
        analysis_id = "analysis-1"

        eps = [
            {
                "endpoint_id": "ep-regex",
                "http_method": "GET",
                "raw_path": "/users/{id:[0-9]+}",
                "normalized_exact_path": "",
                "normalized_path_template": "/users/{id:[0-9]+}",
                "is_templated": 1,
                "path_normalization_version": "v1",
                "path_segment_count": 2,
                "static_prefix": "/users",
                "canonical_path_shape": "/users/*",
                "controller_class": "UserController",
                "controller_method": "getUser",
                "controller_method_signature": "User getUser(Long id)",
                "parameters": "id:Long",
                "return_type": "User",
                "source_file": "com/example/UserController.java",
                "source_start_line": 60,
                "source_start_column": 5,
                "source_end_line": 72,
                "source_end_column": 1,
                "entry_call_node_id": "cn-regex",
            },
        ]
        _insert_endpoints(storage, analysis_id, eps)

        matcher = EndpointMatcher()
        db_eps = _read_endpoints(storage, analysis_id)

        req_num = _make_request("req-1", "GET", "/users/12345")
        result = matcher.match_batch([req_num], db_eps)
        assert result.evidence_list[0].resolution_status == ResolutionStatus.UNIQUE

        # 重建 matcher 避免索引复用
        matcher2 = EndpointMatcher()
        req_str = _make_request("req-2", "GET", "/users/abc")
        result2 = matcher2.match_batch([req_str], db_eps)
        assert result2.evidence_list[0].resolution_status == ResolutionStatus.UNMATCHED

    def test_specificity_tie_break_real_db(self, tmp_path: Path) -> None:
        """重叠模板 + specificity 排序 → 选出最具体的唯一匹配。"""
        storage = _make_minimal_db(tmp_path)
        analysis_id = "analysis-1"

        eps = [
            {
                "endpoint_id": "ep-specific",
                "http_method": "GET",
                "raw_path": "/api/v1/users/{id}",
                "normalized_exact_path": "",
                "normalized_path_template": "/api/v1/users/{id}",
                "is_templated": 1,
                "path_normalization_version": "v1",
                "path_segment_count": 4,
                "static_prefix": "/api/v1/users",
                "canonical_path_shape": "/api/v1/users/*",
                "controller_class": "UserControllerV1",
                "controller_method": "getUserV1",
                "controller_method_signature": "User getUserV1(Long id)",
                "parameters": "id:Long",
                "return_type": "User",
                "source_file": "com/example/v1/UserController.java",
                "source_start_line": 30,
                "source_start_column": 5,
                "source_end_line": 45,
                "source_end_column": 1,
                "entry_call_node_id": "cn-v1",
            },
            {
                "endpoint_id": "ep-generic",
                "http_method": "GET",
                "raw_path": "/api/{version}/users/{id}",
                "normalized_exact_path": "",
                "normalized_path_template": "/api/{version}/users/{id}",
                "is_templated": 1,
                "path_normalization_version": "v1",
                "path_segment_count": 4,
                "static_prefix": "/api",
                "canonical_path_shape": "/api/*/users/*",
                "controller_class": "UserController",
                "controller_method": "getUser",
                "controller_method_signature": "User getUser(String version, Long id)",
                "parameters": "version:String,id:Long",
                "return_type": "User",
                "source_file": "com/example/UserController.java",
                "source_start_line": 80,
                "source_start_column": 5,
                "source_end_line": 95,
                "source_end_column": 1,
                "entry_call_node_id": "cn-generic",
            },
        ]
        _insert_endpoints(storage, analysis_id, eps)

        req = _make_request("req-1", "GET", "/api/v1/users/42")
        matcher = EndpointMatcher()
        db_eps = _read_endpoints(storage, analysis_id)
        result = matcher.match_batch([req], db_eps)

        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.matched_endpoint_id == "ep-specific"
        assert len(result.candidates) == 0

    def test_first_segment_param_real_db(self, tmp_path: Path) -> None:
        """首段为 {tenant} 的模板 → 匹配 /acme/users。"""
        storage = _make_minimal_db(tmp_path)
        analysis_id = "analysis-1"

        eps = [
            {
                "endpoint_id": "ep-tenant",
                "http_method": "GET",
                "raw_path": "/{tenant}/users",
                "normalized_exact_path": "",
                "normalized_path_template": "/{tenant}/users",
                "is_templated": 1,
                "path_normalization_version": "v1",
                "path_segment_count": 2,
                "static_prefix": "",
                "canonical_path_shape": "/*/users",
                "controller_class": "TenantController",
                "controller_method": "listUsers",
                "controller_method_signature": "List<User> listUsers(String tenant)",
                "parameters": "tenant:String",
                "return_type": "List<User>",
                "source_file": "com/example/TenantController.java",
                "source_start_line": 25,
                "source_start_column": 5,
                "source_end_line": 38,
                "source_end_column": 1,
                "entry_call_node_id": "cn-tenant",
            },
        ]
        _insert_endpoints(storage, analysis_id, eps)

        req = _make_request("req-1", "GET", "/acme/users")
        matcher = EndpointMatcher()
        db_eps = _read_endpoints(storage, analysis_id)
        result = matcher.match_batch([req], db_eps)

        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.TEMPLATE
        assert ev.matched_endpoint_id == "ep-tenant"

    def test_batch_mixed_results_real_db(self, tmp_path: Path) -> None:
        """批量匹配混合请求 → 分别返回 EXACT/TEMPLATE/UNMATCHED。"""
        storage = _make_minimal_db(tmp_path)
        analysis_id = "analysis-1"

        eps = [
            {
                "endpoint_id": "ep-users",
                "http_method": "GET",
                "raw_path": "/api/users",
                "normalized_exact_path": "/api/users",
                "normalized_path_template": "",
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
                "entry_call_node_id": "cn-users",
            },
            {
                "endpoint_id": "ep-user-by-id",
                "http_method": "GET",
                "raw_path": "/api/users/{id}",
                "normalized_exact_path": "",
                "normalized_path_template": "/api/users/{id}",
                "is_templated": 1,
                "path_normalization_version": "v1",
                "path_segment_count": 3,
                "static_prefix": "/api/users",
                "canonical_path_shape": "/api/users/*",
                "controller_class": "UserController",
                "controller_method": "getUser",
                "controller_method_signature": "User getUser(Long id)",
                "parameters": "id:Long",
                "return_type": "User",
                "source_file": "com/example/UserController.java",
                "source_start_line": 60,
                "source_start_column": 5,
                "source_end_line": 72,
                "source_end_column": 1,
                "entry_call_node_id": "cn-user-by-id",
            },
        ]
        _insert_endpoints(storage, analysis_id, eps)
        db_eps = _read_endpoints(storage, analysis_id)

        reqs = [
            _make_request("req-exact", "GET", "/api/users"),
            _make_request("req-template", "GET", "/api/users/42"),
            _make_request("req-unmatched", "GET", "/api/nonexistent"),
        ]

        matcher = EndpointMatcher()
        result = matcher.match_batch(reqs, db_eps)

        assert len(result.evidence_list) == 3

        ev1 = [e for e in result.evidence_list if e.request_evidence_id == "req-exact"][0]
        assert ev1.match_strategy == MatchStrategy.EXACT
        assert ev1.matched_endpoint_id == "ep-users"

        ev2 = [e for e in result.evidence_list if e.request_evidence_id == "req-template"][0]
        assert ev2.match_strategy == MatchStrategy.TEMPLATE
        assert ev2.matched_endpoint_id == "ep-user-by-id"

        ev3 = [e for e in result.evidence_list if e.request_evidence_id == "req-unmatched"][0]
        assert ev3.resolution_status == ResolutionStatus.UNMATCHED
