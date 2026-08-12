"""阶段四：Finding 证据 + 调用流生成测试 — P2#8。

覆盖：generate_finding_evidence（DIRECT_HANDLER/FLOW_MEMBER/STATIC_REACHABLE/UNKNOWN）
和 generate_flows（端点→执行流关联）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.correlation._execution import (
    _determine_relation_type,
    _format_endpoint_location,
    _line_within_range,
    _parse_finding_location,
    generate_finding_evidence,
    generate_flows,
)
from argus_py.correlation.enums import (
    FindingRelationType,
    MatchConfidence,
    MatchStrategy,
    ResolutionStatus,
)
from argus_py.correlation.models import (
    EndpointEvidence,
)
from argus_py.task.models import Task
from argus_py.task.repositories.analysis_repo import (
    _call_node_to_row,
    _endpoint_to_row,
)
from argus_py.task.storage import TaskSQLiteStorage

pytestmark = [pytest.mark.integration]


def _seed_analysis_data(
    storage: TaskSQLiteStorage,
    analysis_id: str = "analysis-fe",
    task_id: str = "t-fe",
) -> None:
    """写入分析任务 + 端点 + 调用节点 + 执行流 + findings。"""
    task = Task(
        task_id=task_id,
        goal="finding evidence test",
        project_id="p1",
        task_type=TaskType.WHITEBOX,
        status=TaskStatus.COMPLETED,
    )
    storage.save(task)

    # 写入分析执行
    from argus_py.analysis.models import AnalysisRun

    ar = AnalysisRun(
        analysis_id=analysis_id,
        task_id=task_id,
        source_snapshot_id="src-1",
        resolved_commit_sha="abc123",
        run_status="SUCCEEDED",
        config_json="{}",
    )
    storage.create_analysis_run(ar)

    # 写入端点（2 个）

    ep1 = {
        "endpoint_id": "ep-fe-1",
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
        "entry_call_node_id": "cn-1",
    }
    ep2 = {
        "endpoint_id": "ep-fe-2",
        "http_method": "POST",
        "raw_path": "/api/orders",
        "normalized_exact_path": "/api/orders",
        "normalized_path_template": "",
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
    }
    with storage._analysis._pool.tx() as conn:
        for ep in [ep1, ep2]:
            ep.setdefault("endpoint_fingerprint", f"fp:{ep['endpoint_id']}")
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
                _endpoint_to_row(analysis_id, ep),
            )

    # 写入调用节点（2 个）
    cn1 = {
        "call_node_id": "cn-1",
        "class_name": "UserController",
        "method_name": "listUsers",
        "method_signature": "List<User> listUsers()",
        "source_file": "com/example/UserController.java",
        "source_start_line": 42,
        "source_start_column": 5,
        "source_end_line": 55,
        "source_end_column": 1,
    }
    cn2 = {
        "call_node_id": "cn-2",
        "class_name": "OrderController",
        "method_name": "createOrder",
        "method_signature": "Order createOrder(OrderDto dto)",
        "source_file": "com/example/OrderController.java",
        "source_start_line": 80,
        "source_start_column": 5,
        "source_end_line": 100,
        "source_end_column": 1,
    }
    with storage._analysis._pool.tx() as conn:
        for cn in [cn1, cn2]:
            cn.setdefault("call_node_fingerprint", f"fp:{cn['call_node_id']}")
            conn.execute(
                """INSERT OR IGNORE INTO analysis_call_nodes (
                    call_node_id, analysis_id, call_node_fingerprint,
                    class_name, method_name, method_signature,
                    source_file, source_start_line, source_start_column,
                    source_end_line, source_end_column
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _call_node_to_row(analysis_id, cn),
            )

    # 写入执行流（1 条）
    with storage._analysis._pool.tx() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO analysis_execution_flows (
                execution_flow_id, analysis_id, execution_flow_fingerprint,
                entry_point, call_depth
            ) VALUES (?, ?, ?, ?, ?)""",
            ("flow-1", analysis_id, "fp:flow-1", "UserController.listUsers", 2),
        )

    # 写入 flow_steps
    with storage._analysis._pool.tx() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO analysis_flow_steps (
                flow_step_id, execution_flow_id, step_index, depth,
                method_key, class_name, method_name, call_node_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "fs-1",
                "flow-1",
                1,
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
            (
                "fs-2",
                "flow-1",
                2,
                1,
                "OrderController.createOrder",
                "OrderController",
                "createOrder",
                "cn-2",
            ),
        )

    # 写入 findings
    with storage._tasks._pool.tx() as conn:
        for _i, (fid, rule_id, location, url) in enumerate(
            [
                # DIRECT_HANDLER: 行号落在 UserController.listUsers 范围内
                ("f-1", "SQLI-001", "com/example/UserController.java:45", ""),
                # STATIC_REACHABLE: 同文件但行号不在端点范围
                ("f-2", "XSS-001", "com/example/UserController.java:120", ""),
                # URL 匹配：url 包含 /api/orders
                ("f-3", "CSRF-001", "com/example/OtherController.java:10", "/api/orders/create"),
                # UNKNOWN: 无文件匹配，无 URL 匹配
                ("f-4", "AUTH-001", "com/example/Unrelated.java:5", ""),
            ]
        ):
            conn.execute(
                """INSERT OR IGNORE INTO findings (
                    finding_id, task_id, analysis_id, title, description,
                    severity, finding_type, location, url,
                    rule_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fid,
                    task_id,
                    analysis_id,
                    f"Finding {fid}",
                    f"Description for {fid}",
                    "high",
                    "functional",
                    location,
                    url,
                    rule_id,
                    "2024-01-01",
                ),
            )


def _make_evidence(
    ev_id: str, matched_endpoint_id: str | None, req_id: str = "req-1"
) -> EndpointEvidence:
    return EndpointEvidence(
        endpoint_evidence_id=ev_id,
        correlation_run_id="cr-fe",
        correlation_attempt_id="ca-fe",
        request_evidence_id=req_id,
        resolution_status=ResolutionStatus.UNIQUE
        if matched_endpoint_id
        else ResolutionStatus.UNMATCHED,
        match_strategy=MatchStrategy.EXACT if matched_endpoint_id else MatchStrategy.NONE,
        confidence=MatchConfidence.HIGH if matched_endpoint_id else MatchConfidence.UNKNOWN,
        matched_endpoint_id=matched_endpoint_id,
        candidate_count=1,
    )


class TestGenerateFlows:
    """P2#8：generate_flows — 端点到执行流的关联。"""

    def test_generate_flows_links_endpoint_to_flow(self, tmp_path: Path) -> None:
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "flows.db")
        _seed_analysis_data(storage)

        endpoints = storage.list_analysis_endpoints("analysis-fe", limit=1000)[0]
        evidence_list = [_make_evidence("ev-1", "ep-fe-1")]

        flows = generate_flows(storage, "analysis-fe", evidence_list, endpoints)
        assert len(flows) >= 1
        # flow-1 的 entry_point 是 UserController.listUsers，应与 ep-fe-1 匹配
        flow_ids = {f.execution_flow_id for f in flows}
        assert "flow-1" in flow_ids

    def test_generate_flows_no_matching_endpoint_returns_empty(self, tmp_path: Path) -> None:
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "flows.db")
        _seed_analysis_data(storage)

        endpoints = storage.list_analysis_endpoints("analysis-fe", limit=1000)[0]
        # 未匹配的 evidence
        evidence_list = [_make_evidence("ev-1", None)]

        flows = generate_flows(storage, "analysis-fe", evidence_list, endpoints)
        assert len(flows) == 0

    def test_format_endpoint_location(self) -> None:
        """端点源码位置格式化。"""
        assert _format_endpoint_location({}) == ""
        assert (
            _format_endpoint_location(
                {"source_file": "UserController.java", "source_start_line": 42}
            )
            == "UserController.java:42"
        )
        assert (
            _format_endpoint_location({"source_file": "UserController.java"})
            == "UserController.java"
        )


class TestGenerateFindingEvidence:
    """P2#8：generate_finding_evidence — Finding 与端点/请求证据的关联。"""

    def test_direct_handler_finding(self, tmp_path: Path) -> None:
        """行号落在端点范围内 → DIRECT_HANDLER。"""
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "finding.db")
        _seed_analysis_data(storage)

        endpoints = storage.list_analysis_endpoints("analysis-fe", limit=1000)[0]
        evidence_list = [_make_evidence("ev-1", "ep-fe-1")]

        fe_list, fl_list = generate_finding_evidence(
            storage,
            "analysis-fe",
            "ca-fe",
            evidence_list,
            endpoints,
        )

        # f-1 (line 45 in UserController.java) → DIRECT_HANDLER
        f1 = next((fe for fe in fe_list if fe.finding_id == "f-1"), None)
        assert f1 is not None
        assert f1.best_relation_type == FindingRelationType.DIRECT_HANDLER

    def test_static_reachable_finding(self, tmp_path: Path) -> None:
        """同文件但行号不在端点范围 → STATIC_REACHABLE。"""
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "finding.db")
        _seed_analysis_data(storage)

        endpoints = storage.list_analysis_endpoints("analysis-fe", limit=1000)[0]
        evidence_list = [_make_evidence("ev-1", "ep-fe-1")]

        fe_list, fl_list = generate_finding_evidence(
            storage,
            "analysis-fe",
            "ca-fe",
            evidence_list,
            endpoints,
        )

        # f-2 (line 120 in UserController.java) → STATIC_REACHABLE
        f2 = next((fe for fe in fe_list if fe.finding_id == "f-2"), None)
        assert f2 is not None
        assert f2.best_relation_type == FindingRelationType.STATIC_REACHABLE

    def test_url_match_finding(self, tmp_path: Path) -> None:
        """URL 匹配 → DIRECT_HANDLER。"""
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "finding.db")
        _seed_analysis_data(storage)

        endpoints = storage.list_analysis_endpoints("analysis-fe", limit=1000)[0]
        evidence_list = [
            _make_evidence("ev-1", "ep-fe-1"),
            _make_evidence("ev-2", "ep-fe-2"),
        ]

        fe_list, fl_list = generate_finding_evidence(
            storage,
            "analysis-fe",
            "ca-fe",
            evidence_list,
            endpoints,
        )

        # f-3: url contains /api/orders → ep-fe-2 的 raw_path 是 /api/orders
        f3 = next((fe for fe in fe_list if fe.finding_id == "f-3"), None)
        assert f3 is not None
        assert f3.best_relation_type == FindingRelationType.DIRECT_HANDLER

    def test_unknown_finding(self, tmp_path: Path) -> None:
        """无文件匹配、无 URL 匹配 → UNKNOWN。"""
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "finding.db")
        _seed_analysis_data(storage)

        endpoints = storage.list_analysis_endpoints("analysis-fe", limit=1000)[0]
        evidence_list = [_make_evidence("ev-1", "ep-fe-1")]

        fe_list, fl_list = generate_finding_evidence(
            storage,
            "analysis-fe",
            "ca-fe",
            evidence_list,
            endpoints,
        )

        # f-4: com/example/Unrelated.java, line 5 → UNKNOWN
        f4 = next((fe for fe in fe_list if fe.finding_id == "f-4"), None)
        assert f4 is not None
        assert f4.best_relation_type == FindingRelationType.UNKNOWN

    def test_finding_evidence_structure_complete(self, tmp_path: Path) -> None:
        """FindingEvidence 和 FindingEvidenceLink 的字段完整性。"""
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "finding.db")
        _seed_analysis_data(storage)

        endpoints = storage.list_analysis_endpoints("analysis-fe", limit=1000)[0]
        evidence_list = [_make_evidence("ev-1", "ep-fe-1")]

        fe_list, fl_list = generate_finding_evidence(
            storage,
            "analysis-fe",
            "ca-fe",
            evidence_list,
            endpoints,
        )

        assert len(fe_list) == 4  # 4 findings
        for fe in fe_list:
            assert fe.finding_evidence_id.startswith("fe:")
            assert fe.correlation_attempt_id == "ca-fe"
            assert fe.finding_id in {"f-1", "f-2", "f-3", "f-4"}
            assert fe.finding_rule_id_snapshot is not None
            assert isinstance(fe.confirmed_request_count, int)

        # f-1 (DIRECT_HANDLER) → 应生成 FindingEvidenceLink
        # 至少有一条 link
        assert len(fl_list) > 0


class TestDetermineRelationType:
    """_determine_relation_type 的单元测试。"""

    def test_direct_handler_same_file_same_lines(self) -> None:
        endpoint = {
            "source_file": "com/example/UserController.java",
            "source_start_line": 42,
            "source_end_line": 55,
        }
        method_line_index: dict[str, list[tuple[int, int | None, str]]] = {}
        flow_method_index: dict[str, set[str]] = {}
        endpoint_flow_ids: set[str] = set()

        rel = _determine_relation_type(
            "com/example/UserController.java",
            45,
            None,
            endpoint,
            method_line_index,
            flow_method_index,
            endpoint_flow_ids,
        )
        assert rel == FindingRelationType.DIRECT_HANDLER

    def test_static_reachable_same_file_outside_range(self) -> None:
        endpoint = {
            "source_file": "com/example/UserController.java",
            "source_start_line": 42,
            "source_end_line": 55,
        }
        method_line_index: dict[str, list[tuple[int, int | None, str]]] = {}
        flow_method_index: dict[str, set[str]] = {}
        endpoint_flow_ids: set[str] = set()

        rel = _determine_relation_type(
            "com/example/UserController.java",
            120,
            None,
            endpoint,
            method_line_index,
            flow_method_index,
            endpoint_flow_ids,
        )
        assert rel == FindingRelationType.STATIC_REACHABLE

    def test_different_file_unknown(self) -> None:
        endpoint = {
            "source_file": "com/example/UserController.java",
            "source_start_line": 42,
            "source_end_line": 55,
        }
        method_line_index: dict[str, list[tuple[int, int | None, str]]] = {}
        flow_method_index: dict[str, set[str]] = {}
        endpoint_flow_ids: set[str] = set()

        rel = _determine_relation_type(
            "com/example/OrderController.java",
            80,
            None,
            endpoint,
            method_line_index,
            flow_method_index,
            endpoint_flow_ids,
        )
        assert rel == FindingRelationType.UNKNOWN


class TestPreFetchedProjectionDedup:
    """P-H1/P-M2：传入已取全的 flows/call_nodes 与内部取数结果完全一致。

    关联匹配单次取数后，generate_flows / generate_finding_evidence 接收
    预先取全的投影列表，不再重复查询同一投影表；去重必须不改变结果语义。
    """

    def test_generate_flows_identical_with_passed_flows(self, tmp_path: Path) -> None:
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "dedup.db")
        _seed_analysis_data(storage)

        endpoints = storage.list_all_analysis_endpoints("analysis-fe")
        evidence_list = [_make_evidence("ev-1", "ep-fe-1")]
        pre_fetched = storage.list_all_analysis_execution_flows("analysis-fe")

        by_storage = generate_flows(storage, "analysis-fe", evidence_list, endpoints)
        by_passed = generate_flows(
            storage, "analysis-fe", evidence_list, endpoints, flows=pre_fetched
        )
        assert len(by_storage) == len(by_passed)
        assert {(f.endpoint_evidence_id, f.execution_flow_id) for f in by_storage} == {
            (f.endpoint_evidence_id, f.execution_flow_id) for f in by_passed
        }

    def test_generate_finding_evidence_identical_with_passed_projections(
        self, tmp_path: Path
    ) -> None:
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "dedup.db")
        _seed_analysis_data(storage)

        endpoints = storage.list_all_analysis_endpoints("analysis-fe")
        evidence_list = [_make_evidence("ev-1", "ep-fe-1")]
        pre_flows = storage.list_all_analysis_execution_flows("analysis-fe")
        pre_nodes = storage.list_all_analysis_call_nodes("analysis-fe")

        fe_storage, fl_storage = generate_finding_evidence(
            storage, "analysis-fe", "ca-fe", evidence_list, endpoints
        )
        fe_passed, fl_passed = generate_finding_evidence(
            storage,
            "analysis-fe",
            "ca-fe",
            evidence_list,
            endpoints,
            flows=pre_flows,
            call_nodes=pre_nodes,
        )
        assert {fe.finding_id: fe.best_relation_type for fe in fe_storage} == {
            fe.finding_id: fe.best_relation_type for fe in fe_passed
        }
        # finding_evidence_id 为每次调用随机生成，不可直接比较；把两端 fe_id 都归一
        # 为 finding_id 后，按 (finding_id, endpoint_id, relation_type) 结构比较
        # 去重路径与内部取数路径产出的链接等价。
        finding_by_fe_id = {fe.finding_evidence_id: fe.finding_id for fe in fe_storage}
        finding_by_fe_id_passed = {fe.finding_evidence_id: fe.finding_id for fe in fe_passed}
        links_storage = {
            (finding_by_fe_id[fl.finding_evidence_id], fl.endpoint_id, fl.relation_type)
            for fl in fl_storage
        }
        links_passed = {
            (finding_by_fe_id_passed[fl.finding_evidence_id], fl.endpoint_id, fl.relation_type)
            for fl in fl_passed
        }
        assert links_storage == links_passed


class TestParseFindingLocation:
    def test_normal_location(self) -> None:
        file, start, end = _parse_finding_location("com/example/UserController.java:45")
        assert file == "com/example/UserController.java"
        assert start == 45
        assert end is None

    def test_range_location(self) -> None:
        file, start, end = _parse_finding_location("com/example/UserController.java:45-60")
        assert file == "com/example/UserController.java"
        assert start == 45
        assert end == 60

    def test_none_location(self) -> None:
        file, start, end = _parse_finding_location(None)
        assert file == ""
        assert start == 0
        assert end is None

    def test_backslash_normalized(self) -> None:
        file, start, end = _parse_finding_location("com\\example\\UserController.java:45")
        assert file == "com/example/UserController.java"


class TestLineWithinRange:
    def test_within_range(self) -> None:
        assert _line_within_range(45, None, 42, 55) is True

    def test_outside_range(self) -> None:
        assert _line_within_range(120, None, 42, 55) is False

    def test_no_ep_start(self) -> None:
        assert _line_within_range(45, None, None, 55) is False

    def test_single_line_match(self) -> None:
        assert _line_within_range(42, None, 42, 42) is True
