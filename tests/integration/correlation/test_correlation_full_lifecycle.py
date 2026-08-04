"""阶段四：完整生命周期集成测试 — P1#10。

覆盖从创建到激活的完整链路：
1. 创建 BlackboxRun
2. 创建 CorrelationRun (WAITING_ANALYSIS)
3. 白盒分析完成 → 自动绑定 (WAITING_BLACKBOX)
4. 黑盒执行完成 → READY
5. claim_and_create_attempt (真实 CAS)
6. EndpointMatcher 执行匹配
7. 写入 endpoint_evidence + candidates
8. complete_and_activate_attempt (原子发布)
9. API 层面查询校验
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.correlation.enums import (
    BlackboxRunStatus,
    CorrelationEligibility,
    CorrelationRunStatus,
    RequestOutcome,
    RequestOwner,
)
from argus_py.correlation.matcher import EndpointMatcher
from argus_py.correlation.models import (
    BlackboxRun,
    CaptureQuality,
    CorrelationRun,
    HttpRequestEvidence,
)
from argus_py.task.models import Task
from argus_py.task.repositories.analysis_repo import _endpoint_to_row
from argus_py.task.storage import TaskSQLiteStorage

pytestmark = [pytest.mark.integration]


def _seed_full_chain_data(
    storage: TaskSQLiteStorage,
    *,
    project_id: str = "p1",
    analysis_id: str = "analysis-lifecycle",
    blackbox_run_id: str = "bb-lifecycle",
    correlation_run_id: str = "cr-lifecycle",
    correlation_snapshot: str = "abc123",
) -> None:
    """创建完整生命周期所需的全量种子数据。"""
    # 项目（由 _fixtures 创建）
    # 分析任务 + 分析执行
    whitebox_task = Task(
        task_id="t-whitebox-lc",
        goal="lifecycle whitebox",
        project_id=project_id,
        task_type=TaskType.WHITEBOX,
        status=TaskStatus.COMPLETED,
    )
    storage.save(whitebox_task)

    from argus_py.analysis.models import AnalysisRun

    ar = AnalysisRun(
        analysis_id=analysis_id,
        task_id="t-whitebox-lc",
        source_snapshot_id="src-snap-1",
        resolved_commit_sha=correlation_snapshot,
        run_status="SUCCEEDED",
        config_json="{}",
    )
    storage.create_analysis_run(ar)

    # 黑盒任务
    blackbox_task = Task(
        task_id="t-blackbox-lc",
        goal="lifecycle blackbox",
        project_id=project_id,
        task_type=TaskType.BLACKBOX,
        status=TaskStatus.COMPLETED,
    )
    storage.save(blackbox_task)

    # BlackboxRun
    storage.create_blackbox_run(
        BlackboxRun(
            blackbox_run_id=blackbox_run_id,
            task_id="t-blackbox-lc",
            attempt=1,
            status=BlackboxRunStatus.PENDING,
            started_at="2024-01-01T00:00:00",
        )
    )

    # CorrelationRun (WAITING_ANALYSIS)
    storage.create_correlation_run(
        CorrelationRun(
            correlation_run_id=correlation_run_id,
            project_id=project_id,
            blackbox_run_id=blackbox_run_id,
            desired_source_snapshot_id=correlation_snapshot,
            correlation_config_digest="d1",
            matcher_version="v1",
            normalization_version="v1",
            status=CorrelationRunStatus.WAITING_ANALYSIS,
            created_at="2024-01-01T00:00:00",
        )
    )

    # 写入分析端点（白盒投影数据）
    _write_analysis_endpoints(storage, analysis_id)

    # 写入采集质量
    storage.upsert_capture_quality(
        CaptureQuality(
            blackbox_run_id=blackbox_run_id,
            total_observed=50,
            persisted_count=48,
            updated_at="2024-01-01T00:00:00",
        )
    )


def _write_analysis_endpoints(storage: TaskSQLiteStorage, analysis_id: str) -> None:
    """写入分析端点投影数据。"""
    endpoints = [
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
                _endpoint_to_row(analysis_id, ep),
            )


def _write_request_evidence(storage: TaskSQLiteStorage, blackbox_run_id: str, task_id: str) -> None:
    """写入采集的 HTTP 请求证据。"""
    requests = [
        HttpRequestEvidence(
            request_evidence_id=f"req-lc-{i}",
            blackbox_run_id=blackbox_run_id,
            task_id=task_id,
            step_execution_id=f"{blackbox_run_id}:step:0:attempt:1",
            step_attempt=1,
            request_sequence=i,
            http_method=method,
            normalized_path=path,
            display_path=path,
            origin="https://example.com",
            resource_type="fetch",
            endpoint_match_eligibility=CorrelationEligibility.CONFIRMED_ELIGIBLE,
            outcome=RequestOutcome.COMPLETED,
            request_owner=RequestOwner.FRAME,
            captured_at="2024-01-01T00:00:00",
        )
        for i, (method, path) in enumerate(
            [
                ("GET", "/api/users"),
                ("GET", "/api/users/42"),
                ("GET", "/api/nonexistent"),
            ],
            start=1,
        )
    ]
    storage.insert_http_request_batch(requests)


class TestFullLifecycle:
    """P1#10：创建 → 绑定 → 执行 → 激活 完整链路。"""

    def test_full_chain_waiting_to_ready_to_activated(self, tmp_path: Path) -> None:
        """完整生命周期：WAITING_ANALYSIS → WAITING_BLACKBOX → READY → 匹配 → 激活。"""
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "lifecycle.db")

        # ── Step 1: 创建所有种子数据（模拟任务创建阶段）──
        _seed_full_chain_data(storage)
        _write_request_evidence(storage, "bb-lifecycle", "t-blackbox-lc")

        cr_id = "cr-lifecycle"
        analysis_id = "analysis-lifecycle"

        # ── Step 2: 验证 WAITING_ANALYSIS 可被正确查找 ──
        waiting = storage.find_waiting_correlations("abc123", project_id="p1")
        assert len(waiting) == 1
        assert waiting[0].correlation_run_id == cr_id
        assert waiting[0].status == CorrelationRunStatus.WAITING_ANALYSIS

        # ── Step 3: 绑定分析（模拟 _on_whitebox_analysis_succeeded）──
        storage.bind_correlation_analysis(
            cr_id,
            analysis_id,
            "abc123",
            projection_version=1,
            alignment="VERIFIED",
        )

        bound_cr = storage.get_correlation_run(cr_id)
        assert bound_cr is not None
        assert bound_cr.analysis_id == analysis_id

        # ── Step 4: 黑盒完成后推进到 READY ──
        storage.update_blackbox_run_status(
            "bb-lifecycle", BlackboxRunStatus.SUCCESS.value, "2024-01-01T00:01:00"
        )
        bb = storage.get_blackbox_run("bb-lifecycle")
        bb_done = bb is not None and bb.status in (
            BlackboxRunStatus.SUCCESS,
            BlackboxRunStatus.FAILED,
        )
        assert bb_done
        storage.set_correlation_status(cr_id, "READY")

        ready_cr = storage.get_correlation_run(cr_id)
        assert ready_cr is not None
        assert ready_cr.status == CorrelationRunStatus.READY

        # ── Step 5: 认领 Attempt（真实 CAS）──
        attempt = storage.claim_and_create_attempt(cr_id, "worker-lc")
        assert attempt is not None
        assert attempt.correlation_run_id == cr_id
        assert attempt.attempt_number == 1
        assert attempt.analysis_id == analysis_id

        # ── Step 6: 执行匹配 ──
        endpoints_result = storage.list_analysis_endpoints(analysis_id, limit=1000)
        endpoints = endpoints_result[0]
        assert len(endpoints) == 2

        eligible_requests = storage.list_eligible_requests("bb-lifecycle")
        assert len(eligible_requests) == 3

        matcher = EndpointMatcher(matcher_version="v1", normalization_version="v1")
        result = matcher.match_batch(eligible_requests, endpoints)
        assert len(result.evidence_list) == 3

        # ── Step 7: 填充 run/attempt ID 并写入证据 ──
        for ev in result.evidence_list:
            ev.correlation_run_id = cr_id
            ev.correlation_attempt_id = attempt.correlation_attempt_id

        storage.insert_endpoint_evidence_batch(result.evidence_list)

        # ── Step 8: 激活 Attempt ──
        storage.complete_and_activate_attempt(
            attempt.correlation_attempt_id, "SUCCEEDED", completeness="COMPLETE"
        )

        # ── Step 9: 验证最终状态 ──
        activated_cr = storage.get_correlation_run(cr_id)
        assert activated_cr is not None
        assert activated_cr.status == CorrelationRunStatus.SUCCEEDED
        assert activated_cr.active_attempt_id == attempt.correlation_attempt_id

        # 验证 Summary 可查询
        summary = storage.get_correlation_summary(cr_id)
        assert summary.captured_request_count >= 3
        assert summary.confirmed_matched_request_count >= 2
        assert summary.unmatched_request_count >= 1
        assert summary.evidence_completeness == "COMPLETE"

    def test_full_chain_no_eligible_requests(self, tmp_path: Path) -> None:
        """无 eligible 请求时，关联尝试为 SUCCEEDED（COMPLETE）且记录诊断。"""
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "no_eligible.db")
        _seed_full_chain_data(storage)
        # 不写请求证据 → list_eligible_requests 返回空

        cr_id = "cr-lifecycle"
        analysis_id = "analysis-lifecycle"

        # 绑定 + 推进到 READY
        storage.bind_correlation_analysis(
            cr_id,
            analysis_id,
            "abc123",
            projection_version=1,
            alignment="VERIFIED",
        )
        storage.update_blackbox_run_status(
            "bb-lifecycle", BlackboxRunStatus.SUCCESS.value, "2024-01-01T00:01:00"
        )
        storage.set_correlation_status(cr_id, "READY")
        attempt = storage.claim_and_create_attempt(cr_id, "worker-no-eligible")
        assert attempt is not None

        # 无 eligible 请求 → 直接完成
        eligible = storage.list_eligible_requests("bb-lifecycle")
        assert len(eligible) == 0

        storage.complete_and_activate_attempt(
            attempt.correlation_attempt_id, "SUCCEEDED", completeness="COMPLETE"
        )

        activated_cr = storage.get_correlation_run(cr_id)
        assert activated_cr is not None
        assert activated_cr.status == CorrelationRunStatus.SUCCEEDED

    def test_full_chain_with_truncated_capture(self, tmp_path: Path) -> None:
        """采集截断 → completeness 为 PARTIAL。"""
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "truncated.db")
        _seed_full_chain_data(storage)
        _write_request_evidence(storage, "bb-lifecycle", "t-blackbox-lc")

        # 覆盖 CaptureQuality 为截断状态
        storage.upsert_capture_quality(
            CaptureQuality(
                blackbox_run_id="bb-lifecycle",
                total_observed=500,
                persisted_count=100,
                truncated=True,
                truncation_reason="采集量超限",
                updated_at="2024-01-01T00:00:00",
            )
        )

        cr_id = "cr-lifecycle"
        analysis_id = "analysis-lifecycle"

        storage.bind_correlation_analysis(
            cr_id,
            analysis_id,
            "abc123",
            projection_version=1,
            alignment="VERIFIED",
        )
        storage.update_blackbox_run_status(
            "bb-lifecycle", BlackboxRunStatus.SUCCESS.value, "2024-01-01T00:01:00"
        )
        storage.set_correlation_status(cr_id, "READY")
        attempt = storage.claim_and_create_attempt(cr_id, "worker-truncated")
        assert attempt is not None

        # 执行匹配
        endpoints = storage.list_analysis_endpoints(analysis_id, limit=1000)[0]
        eligible = storage.list_eligible_requests("bb-lifecycle")
        matcher = EndpointMatcher()
        result = matcher.match_batch(eligible, endpoints)

        for ev in result.evidence_list:
            ev.correlation_run_id = cr_id
            ev.correlation_attempt_id = attempt.correlation_attempt_id
        storage.insert_endpoint_evidence_batch(result.evidence_list)

        # 截断 → PARTIAL
        cq = storage.get_capture_quality("bb-lifecycle")
        from argus_py.correlation._execution import (
            assess_capture_quality,
            build_quality_reasons,
            resolve_completeness,
        )

        capture_truncated, has_persistence_failure = assess_capture_quality(cq)
        assert capture_truncated is True

        reasons, diagnostics = build_quality_reasons(
            attempt.correlation_attempt_id,
            cq,
            capture_truncated,
            has_persistence_failure,
        )
        assert len(reasons) == 1
        assert reasons[0].reason_code.value == "CAPTURE_TRUNCATED"

        storage.insert_attempt_reasons_batch(reasons)
        completeness = resolve_completeness(
            bool(reasons),
            capture_truncated,
            has_persistence_failure,
        )
        assert completeness.value == "PARTIAL"

        storage.complete_and_activate_attempt(
            attempt.correlation_attempt_id, "PARTIAL", completeness="PARTIAL"
        )

        activated_cr = storage.get_correlation_run(cr_id)
        assert activated_cr is not None
        summary = storage.get_correlation_summary(cr_id)
        assert summary.evidence_completeness == "PARTIAL"

    def test_full_chain_idempotent_correlation_run_creation(self, tmp_path: Path) -> None:
        """P0 回归：同一 blackbox_run_id 创建两次 CorrelationRun → 幂等返回已有。"""
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "idempotent.db")
        _seed_full_chain_data(storage)

        # 再次创建相同 blackbox_run_id 的 CorrelationRun → 应抛出唯一索引冲突
        cr2 = CorrelationRun(
            correlation_run_id="cr-dup",
            project_id="p1",
            blackbox_run_id="bb-lifecycle",  # 已存在
            desired_source_snapshot_id="abc123",
            correlation_config_digest="d1",
            matcher_version="v1",
            normalization_version="v1",
            status=CorrelationRunStatus.WAITING_ANALYSIS,
            created_at="2024-01-01T00:00:00",
        )
        try:
            storage.create_correlation_run(cr2)
        except Exception:
            existing = storage.get_correlation_run_by_blackbox("bb-lifecycle")
            assert existing is not None
            assert existing.correlation_run_id == "cr-lifecycle"
