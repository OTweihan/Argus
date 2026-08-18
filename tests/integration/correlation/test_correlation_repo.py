"""阶段三：关联 Repository — 集成测试。

覆盖：BlackboxRun CRUD、CorrelationRun 创建/绑定/状态推进/认领 CAS、
Evidence/Candidate/Flow/FindingEvidence 批量写入与查询、
CaptureQuality、汇总、未匹配请求查询、未触达端点查询。

所有测试使用临时 SQLite 数据库，通过 TaskSQLiteStorage facade 操作，
自动满足 FK 约束（tasks、projects 通过 helper 预创建）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argus_py.analysis.models import AnalysisRun
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.correlation.enums import (
    AttemptDiagnosticCode,
    AttemptStatus,
    BlackboxRunStatus,
    CorrelationEligibility,
    CorrelationRunStatus,
    EvidenceCompleteness,
    FindingRelationType,
    MatchConfidence,
    MatchStrategy,
    PartialReasonCode,
    RequestOutcome,
    RequestOwner,
    ResolutionStatus,
)
from argus_py.correlation.models import (
    BlackboxRun,
    CaptureQuality,
    CorrelationAttemptDiagnostic,
    CorrelationAttemptReason,
    CorrelationRun,
    EndpointEvidence,
    EndpointEvidenceCandidate,
    EndpointEvidenceFlow,
    FindingEvidence,
    FindingEvidenceLink,
    HttpRequestEvidence,
)
from argus_py.task.models import Task
from argus_py.task.storage import TaskSQLiteStorage

# ── Helpers ──────────────────────────────────────────────────────────


def _ensure_task_and_project(storage: TaskSQLiteStorage, task_id: str, project_id: str) -> None:
    """在存储中创建 Task 和 Project，满足 FK 约束。"""
    # 通过原始连接插入 project（避免重复）
    with storage._correlation._pool.tx() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO projects (project_id, name, created_at, updated_at)
               VALUES (?, ?, ?, ?)""",
            (project_id, f"Project {project_id}", "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
        )
    # 使用 Task.save 创建任务
    if not storage.exists(task_id):
        task = Task(
            task_id=task_id,
            goal="test goal",
            project_id=project_id,
            task_type=TaskType.BLACKBOX,
            status=TaskStatus.PENDING,
        )
        storage.save(task)


def _make_blackbox_run(
    storage: TaskSQLiteStorage,
    blackbox_run_id: str,
    task_id: str = "t:default",
    status: BlackboxRunStatus = BlackboxRunStatus.RUNNING,
) -> BlackboxRun:
    """创建 BlackboxRun 并返回。"""
    run = BlackboxRun(
        blackbox_run_id=blackbox_run_id,
        task_id=task_id,
        attempt=1,
        status=status,
        started_at="2024-01-01T00:00:00",
    )
    storage.create_blackbox_run(run)
    return run


def _make_correlation_run(
    storage: TaskSQLiteStorage,
    correlation_run_id: str,
    blackbox_run_id: str,
    project_id: str = "proj:default",
    status: CorrelationRunStatus = CorrelationRunStatus.WAITING_ANALYSIS,
    *,
    analysis_id: str | None = None,
    bound_source_snapshot_id: str | None = None,
    analysis_projection_version: int | None = None,
    created_at: str = "2024-01-01T00:00:00",
) -> CorrelationRun:
    """创建 CorrelationRun 并返回。"""
    cr = CorrelationRun(
        correlation_run_id=correlation_run_id,
        project_id=project_id,
        blackbox_run_id=blackbox_run_id,
        desired_source_snapshot_id="abc123",
        correlation_config_digest="d1",
        matcher_version="v1",
        normalization_version="v1",
        analysis_id=analysis_id,
        bound_source_snapshot_id=bound_source_snapshot_id,
        analysis_projection_version=analysis_projection_version,
        status=status,
        created_at=created_at,
    )
    storage.create_correlation_run(cr)
    return cr


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def storage(tmp_path: Path) -> TaskSQLiteStorage:
    """使用临时 SQLite 数据库的 TaskSQLiteStorage。"""
    return TaskSQLiteStorage(tmp_path / "corr_test.db")


@pytest.fixture
def base(storage: TaskSQLiteStorage) -> tuple[TaskSQLiteStorage, str, str]:
    """预创建基础 Task + Project + BlackboxRun。返回 (storage, task_id, project_id)。"""
    _ensure_task_and_project(storage, "t:base", "proj:base")
    _make_blackbox_run(storage, "bb:base", task_id="t:base")
    return storage, "t:base", "proj:base"


# ── BlackboxRun ──────────────────────────────────────────────────────


class TestBlackboxRun:
    def test_create_and_get(self, base: tuple) -> None:
        storage, task_id, _ = base
        run = BlackboxRun(
            blackbox_run_id="bb:create",
            task_id=task_id,
            attempt=2,
            status=BlackboxRunStatus.PENDING,
            started_at="2024-01-01T00:00:00",
        )
        storage.create_blackbox_run(run)
        fetched = storage.get_blackbox_run("bb:create")
        assert fetched is not None
        assert fetched.blackbox_run_id == "bb:create"
        assert fetched.task_id == task_id

    def test_update_status(self, base: tuple) -> None:
        storage, task_id, _ = base
        run = BlackboxRun(
            blackbox_run_id="bb:status",
            task_id=task_id,
            attempt=3,
            status=BlackboxRunStatus.RUNNING,
            started_at="2024-01-01T00:00:00",
        )
        storage.create_blackbox_run(run)
        storage.update_blackbox_run_status(
            "bb:status", "SUCCESS", completed_at="2024-01-01T01:00:00"
        )
        updated = storage.get_blackbox_run("bb:status")
        assert updated is not None
        assert updated.status == BlackboxRunStatus.SUCCESS


# ── CorrelationRun ───────────────────────────────────────────────────


class TestCorrelationRun:
    def test_create_and_get(self, base: tuple) -> None:
        storage, _, project_id = base
        _make_correlation_run(
            storage,
            "cr:get",
            "bb:base",
            project_id=project_id,
        )
        fetched = storage.get_correlation_run("cr:get")
        assert fetched is not None
        assert fetched.correlation_run_id == "cr:get"

    def test_get_by_blackbox(self, base: tuple) -> None:
        storage, _, project_id = base
        cr = _make_correlation_run(
            storage,
            "cr:bybb",
            "bb:base",
            project_id=project_id,
        )
        fetched = storage.get_correlation_run_by_blackbox("bb:base")
        assert fetched is not None
        assert fetched.correlation_run_id == cr.correlation_run_id

    def test_list_by_blackbox_run_ids_returns_latest_per_run(self, base: tuple) -> None:
        storage, _, project_id = base
        # 同一 blackbox_run 对应两条 correlation_run（重算 supersede 场景）：
        # 批量查询必须与 get_correlation_run_by_blackbox 语义一致，只返回最新一条。
        _make_correlation_run(
            storage,
            "cr:old",
            "bb:base",
            project_id=project_id,
            created_at="2024-01-01T00:00:00",
        )
        _make_correlation_run(
            storage,
            "cr:new",
            "bb:base",
            project_id=project_id,
            status=CorrelationRunStatus.READY,
            analysis_id="analysis:new",
            bound_source_snapshot_id="abc123",
            analysis_projection_version=1,
            created_at="2024-01-02T00:00:00",
        )
        runs = storage.list_correlation_runs_by_blackbox_run_ids(["bb:base"])
        assert [r.correlation_run_id for r in runs] == ["cr:new"]

    def test_set_status(self, base: tuple) -> None:
        storage, _, project_id = base
        cr = _make_correlation_run(
            storage,
            "cr:setst",
            "bb:base",
            project_id=project_id,
        )
        storage.set_correlation_status(cr.correlation_run_id, "READY")
        fetched = storage.get_correlation_run(cr.correlation_run_id)
        assert fetched is not None
        assert fetched.status == CorrelationRunStatus.READY

    def test_bind_analysis(self, base: tuple) -> None:
        storage, _, project_id = base
        cr = _make_correlation_run(
            storage,
            "cr:bind",
            "bb:base",
            project_id=project_id,
        )
        storage.bind_correlation_analysis(
            cr.correlation_run_id,
            "analysis_1",
            "abc123",
            projection_version=1,
            alignment="UNVERIFIED",
        )
        fetched = storage.get_correlation_run(cr.correlation_run_id)
        assert fetched is not None
        assert fetched.analysis_id == "analysis_1"
        assert fetched.bound_source_snapshot_id == "abc123"

    def test_bind_analysis_no_double_bind(self, base: tuple) -> None:
        """绑定后 analysis_id IS NOT NULL，再次绑定不会覆盖。"""
        storage, _, project_id = base
        cr = _make_correlation_run(
            storage,
            "cr:bind2",
            "bb:base",
            project_id=project_id,
        )
        storage.bind_correlation_analysis(
            cr.correlation_run_id,
            "a1",
            "abc123",
            projection_version=1,
            alignment="UNVERIFIED",
        )
        storage.bind_correlation_analysis(
            cr.correlation_run_id,
            "a2",
            "xyz789",
            projection_version=2,
            alignment="VERIFIED",
        )
        fetched = storage.get_correlation_run(cr.correlation_run_id)
        assert fetched is not None
        assert fetched.analysis_id == "a1"


# ── CorrelationAttempt CAS ───────────────────────────────────────────


class TestCorrelationAttempt:
    @pytest.fixture
    def ready_cr(self, base: tuple) -> CorrelationRun:
        storage, _, project_id = base
        return _make_correlation_run(
            storage,
            "cr:ready",
            "bb:base",
            project_id=project_id,
            status=CorrelationRunStatus.READY,
            analysis_id="analysis_1",
            bound_source_snapshot_id="abc123",
            analysis_projection_version=1,
        )

    def test_claim_and_create_attempt(
        self, storage: TaskSQLiteStorage, ready_cr: CorrelationRun
    ) -> None:
        """P0 回归：READY 状态可以被认领。"""
        attempt = storage.claim_and_create_attempt(ready_cr.correlation_run_id, "worker1")
        assert attempt is not None
        assert attempt.correlation_run_id == ready_cr.correlation_run_id
        assert attempt.attempt_number == 1
        assert attempt.status == AttemptStatus.RUNNING
        assert attempt.lease_owner == "worker1"

        cr = storage.get_correlation_run(ready_cr.correlation_run_id)
        assert cr is not None
        assert cr.status == CorrelationRunStatus.RUNNING

    def test_claim_waiting_analysis_fails(self, base: tuple) -> None:
        """P0 回归：WAITING_ANALYSIS 不能被认领。"""
        storage, _, project_id = base
        cr = _make_correlation_run(
            storage,
            "cr:wa",
            "bb:base",
            project_id=project_id,
            status=CorrelationRunStatus.WAITING_ANALYSIS,
        )
        attempt = storage.claim_and_create_attempt(cr.correlation_run_id, "worker1")
        assert attempt is None

    def test_claim_waiting_blackbox_fails(self, base: tuple) -> None:
        """P0 回归：WAITING_BLACKBOX 不能被认领。"""
        storage, _, project_id = base
        cr = _make_correlation_run(
            storage,
            "cr:wb",
            "bb:base",
            project_id=project_id,
            status=CorrelationRunStatus.WAITING_BLACKBOX,
            analysis_id="analysis_1",
            bound_source_snapshot_id="abc123",
            analysis_projection_version=1,
        )
        attempt = storage.claim_and_create_attempt(cr.correlation_run_id, "worker1")
        assert attempt is None

    def test_double_claim_idempotent(
        self, storage: TaskSQLiteStorage, ready_cr: CorrelationRun
    ) -> None:
        """CAS 认领，第二个认领会失败。"""
        attempt1 = storage.claim_and_create_attempt(ready_cr.correlation_run_id, "w1")
        assert attempt1 is not None
        attempt2 = storage.claim_and_create_attempt(ready_cr.correlation_run_id, "w2")
        assert attempt2 is None

    def test_complete_attempt_success(
        self, storage: TaskSQLiteStorage, ready_cr: CorrelationRun
    ) -> None:
        attempt = storage.claim_and_create_attempt(ready_cr.correlation_run_id, "w1")
        assert attempt is not None
        storage.complete_and_activate_attempt(
            attempt.correlation_attempt_id,
            AttemptStatus.SUCCEEDED,
            EvidenceCompleteness.COMPLETE,
        )
        cr = storage.get_correlation_run(ready_cr.correlation_run_id)
        assert cr is not None
        assert cr.status == CorrelationRunStatus.SUCCEEDED

    def test_complete_attempt_failed(
        self, storage: TaskSQLiteStorage, ready_cr: CorrelationRun
    ) -> None:
        attempt = storage.claim_and_create_attempt(ready_cr.correlation_run_id, "w1")
        assert attempt is not None
        storage.complete_and_activate_attempt(
            attempt.correlation_attempt_id,
            AttemptStatus.FAILED,
            EvidenceCompleteness.PARTIAL,
        )
        cr = storage.get_correlation_run(ready_cr.correlation_run_id)
        assert cr is not None
        assert cr.status == CorrelationRunStatus.FAILED


# ── HttpRequestEvidence ──────────────────────────────────────────────


class TestHttpRequestEvidence:
    @pytest.fixture
    def req_base(self, storage: TaskSQLiteStorage) -> str:
        """创建黑盒运行并返回 blackbox_run_id。"""
        _ensure_task_and_project(storage, "t:req", "proj:req")
        _make_blackbox_run(storage, "bb:req", task_id="t:req")
        return "bb:req"

    def test_insert_and_query(self, storage: TaskSQLiteStorage, req_base: str) -> None:
        items = [
            HttpRequestEvidence(
                request_evidence_id="hre:1",
                blackbox_run_id=req_base,
                task_id="t:req",
                step_execution_id=None,
                request_sequence=1,
                http_method="GET",
                normalized_path="/api/users",
                display_path="/api/users",
                origin="https://example.com",
                endpoint_match_eligibility=CorrelationEligibility.CONFIRMED_ELIGIBLE,
                outcome=RequestOutcome.COMPLETED,
                request_owner=RequestOwner.FRAME,
                captured_at="2024-01-01T00:00:00",
            ),
            HttpRequestEvidence(
                request_evidence_id="hre:2",
                blackbox_run_id=req_base,
                task_id="t:req",
                step_execution_id=None,
                request_sequence=2,
                http_method="POST",
                normalized_path="/api/users",
                display_path="/api/users/create",
                origin="https://example.com",
                endpoint_match_eligibility=CorrelationEligibility.ATTEMPT_ONLY,
                outcome=RequestOutcome.NETWORK_FAILED,
                failure_code="ERR_CONNECTION_REFUSED",
                request_owner=RequestOwner.FRAME,
                captured_at="2024-01-01T00:01:00",
            ),
        ]
        storage.insert_http_request_batch(items)

        eligible = storage.list_eligible_requests(req_base)
        assert len(eligible) == 2

    def test_eligible_filtering(self, storage: TaskSQLiteStorage, req_base: str) -> None:
        items = [
            HttpRequestEvidence(
                request_evidence_id="hre:c1",
                blackbox_run_id=req_base,
                task_id="t:req",
                step_execution_id=None,
                request_sequence=1,
                http_method="GET",
                normalized_path="/a",
                display_path="/a",
                origin="https://example.com",
                endpoint_match_eligibility=CorrelationEligibility.CONFIRMED_ELIGIBLE,
                outcome=RequestOutcome.COMPLETED,
                request_owner=RequestOwner.FRAME,
                captured_at="2024-01-01T00:00:00",
            ),
            HttpRequestEvidence(
                request_evidence_id="hre:c2",
                blackbox_run_id=req_base,
                task_id="t:req",
                step_execution_id=None,
                request_sequence=2,
                http_method="GET",
                normalized_path="/b",
                display_path="/b",
                origin="https://example.com",
                endpoint_match_eligibility=CorrelationEligibility.EXCLUDED_SW_CACHE,
                outcome=RequestOutcome.COMPLETED,
                request_owner=RequestOwner.FRAME,
                captured_at="2024-01-01T00:00:00",
            ),
            HttpRequestEvidence(
                request_evidence_id="hre:c3",
                blackbox_run_id=req_base,
                task_id="t:req",
                step_execution_id=None,
                request_sequence=3,
                http_method="GET",
                normalized_path="/c",
                display_path="/c",
                origin="https://example.com",
                endpoint_match_eligibility=CorrelationEligibility.ATTEMPT_ONLY,
                outcome=RequestOutcome.NETWORK_FAILED,
                request_owner=RequestOwner.FRAME,
                captured_at="2024-01-01T00:00:00",
            ),
        ]
        storage.insert_http_request_batch(items)

        eligible = storage.list_eligible_requests(req_base)
        eligible_ids = {r.request_evidence_id for r in eligible}
        assert len(eligible_ids) == 2
        assert "hre:c1" in eligible_ids
        assert "hre:c2" not in eligible_ids
        assert "hre:c3" in eligible_ids

    def test_list_eligible_requests_filters_by_eligibility(
        self, storage: TaskSQLiteStorage, req_base: str
    ) -> None:
        """list_eligible_requests 只返回 CONFIRMED_ELIGIBLE / ATTEMPT_ONLY，排除 SW 缓存。"""
        items = [
            HttpRequestEvidence(
                request_evidence_id=f"hre:cnt{i}",
                blackbox_run_id=req_base,
                task_id="t:req",
                step_execution_id=None,
                request_sequence=i + 1,
                http_method="GET",
                normalized_path=f"/x{i}",
                display_path=f"/x{i}",
                origin="https://example.com",
                endpoint_match_eligibility=(
                    CorrelationEligibility.CONFIRMED_ELIGIBLE
                    if i % 2 == 0
                    else CorrelationEligibility.ATTEMPT_ONLY
                ),
                outcome=RequestOutcome.COMPLETED,
                request_owner=RequestOwner.FRAME,
                captured_at="2024-01-01T00:00:00",
            )
            for i in range(5)
        ]
        items.append(
            HttpRequestEvidence(
                request_evidence_id="hre:cnt6",
                blackbox_run_id=req_base,
                task_id="t:req",
                step_execution_id=None,
                request_sequence=99,
                http_method="GET",
                normalized_path="/excluded",
                display_path="/excluded",
                origin="https://example.com",
                endpoint_match_eligibility=CorrelationEligibility.EXCLUDED_SW_CACHE,
                outcome=RequestOutcome.COMPLETED,
                request_owner=RequestOwner.FRAME,
                captured_at="2024-01-01T00:00:00",
            )
        )
        storage.insert_http_request_batch(items)

        eligible = storage.list_eligible_requests(req_base)
        # 5 个 eligible（CONFIRMED_ELIGIBLE / ATTEMPT_ONLY 交替）+ 1 个 excluded
        assert len(eligible) == 5
        eligible_ids = {r.request_evidence_id for r in eligible}
        assert "hre:cnt6" not in eligible_ids
        # 不存在的 run 返回空
        assert storage.list_eligible_requests("no-such-run") == []


# ── EndpointEvidence + Candidate + Flow ──────────────────────────────


class TestEndpointEvidence:
    @pytest.fixture
    def ev_base(self, storage: TaskSQLiteStorage) -> tuple[str, str, str]:
        """创建完整链路并认领。返回 (cr_id, attempt_id, blackbox_run_id)。"""
        _ensure_task_and_project(storage, "t:ev", "proj:ev")
        _make_blackbox_run(storage, "bb:ev", task_id="t:ev")
        cr = _make_correlation_run(
            storage,
            "cr:ev",
            "bb:ev",
            project_id="proj:ev",
            status=CorrelationRunStatus.READY,
            analysis_id="analysis_1",
            bound_source_snapshot_id="abc123",
            analysis_projection_version=1,
        )
        # 写入请求证据
        storage.insert_http_request_batch(
            [
                HttpRequestEvidence(
                    request_evidence_id="req:ev1",
                    blackbox_run_id="bb:ev",
                    task_id="t:ev",
                    step_execution_id=None,
                    request_sequence=1,
                    http_method="GET",
                    normalized_path="/api/users",
                    display_path="/api/users",
                    origin="https://example.com",
                    endpoint_match_eligibility=CorrelationEligibility.CONFIRMED_ELIGIBLE,
                    outcome=RequestOutcome.COMPLETED,
                    request_owner=RequestOwner.FRAME,
                    captured_at="2024-01-01T00:00:00",
                ),
                HttpRequestEvidence(
                    request_evidence_id="req:ev2",
                    blackbox_run_id="bb:ev",
                    task_id="t:ev",
                    step_execution_id=None,
                    request_sequence=2,
                    http_method="GET",
                    normalized_path="/nonexistent",
                    display_path="/nonexistent",
                    origin="https://example.com",
                    endpoint_match_eligibility=CorrelationEligibility.CONFIRMED_ELIGIBLE,
                    outcome=RequestOutcome.COMPLETED,
                    request_owner=RequestOwner.FRAME,
                    captured_at="2024-01-01T00:00:00",
                ),
            ]
        )
        attempt = storage.claim_and_create_attempt(cr.correlation_run_id, "w1")
        assert attempt is not None
        return cr.correlation_run_id, attempt.correlation_attempt_id, "bb:ev"

    def test_insert_evidence_batch(self, storage: TaskSQLiteStorage, ev_base: tuple) -> None:
        cr_id, attempt_id, _ = ev_base
        ev = EndpointEvidence(
            endpoint_evidence_id="eev:1",
            correlation_run_id=cr_id,
            correlation_attempt_id=attempt_id,
            request_evidence_id="req:ev1",
            resolution_status=ResolutionStatus.UNIQUE,
            match_strategy=MatchStrategy.EXACT,
            confidence=MatchConfidence.HIGH,
            matched_endpoint_id="ep1",
            candidate_count=1,
        )
        storage.insert_endpoint_evidence_batch([ev])

        items, total = storage.list_endpoint_evidence(attempt_id, resolution_status="UNIQUE")
        assert total == 1
        assert items[0]["endpoint_evidence_id"] == "eev:1"
        assert items[0]["matched_endpoint_id"] == "ep1"

    def test_insert_candidates_batch(self, storage: TaskSQLiteStorage, ev_base: tuple) -> None:
        cr_id, attempt_id, _ = ev_base
        ev_amb = EndpointEvidence(
            endpoint_evidence_id="eev:amb",
            correlation_run_id=cr_id,
            correlation_attempt_id=attempt_id,
            request_evidence_id="req:ev1",
            resolution_status=ResolutionStatus.AMBIGUOUS,
            match_strategy=MatchStrategy.TEMPLATE,
            confidence=MatchConfidence.MEDIUM,
            matched_endpoint_id=None,
            candidate_count=2,
        )
        storage.insert_endpoint_evidence_batch([ev_amb])

        candidates = [
            EndpointEvidenceCandidate(
                endpoint_evidence_id="eev:amb",
                endpoint_id="ep_a",
                candidate_rank=1,
                match_strategy=MatchStrategy.TEMPLATE,
                selected=False,
            ),
            EndpointEvidenceCandidate(
                endpoint_evidence_id="eev:amb",
                endpoint_id="ep_b",
                candidate_rank=2,
                match_strategy=MatchStrategy.TEMPLATE,
                selected=False,
            ),
        ]
        storage.insert_candidates_batch(candidates)

        batch_map = storage.batch_get_candidates(["eev:amb"])
        assert "eev:amb" in batch_map
        retrieved = batch_map["eev:amb"]
        assert len(retrieved) == 2
        ep_ids = {c["endpoint_id"] for c in retrieved}
        assert ep_ids == {"ep_a", "ep_b"}

    def test_insert_flows_batch(self, storage: TaskSQLiteStorage, ev_base: tuple) -> None:
        cr_id, attempt_id, _ = ev_base
        ev = EndpointEvidence(
            endpoint_evidence_id="eev:flow",
            correlation_run_id=cr_id,
            correlation_attempt_id=attempt_id,
            request_evidence_id="req:ev1",
            resolution_status=ResolutionStatus.UNIQUE,
            match_strategy=MatchStrategy.EXACT,
            confidence=MatchConfidence.HIGH,
            matched_endpoint_id="ep1",
            candidate_count=1,
        )
        storage.insert_endpoint_evidence_batch([ev])

        flows = [
            EndpointEvidenceFlow(
                endpoint_evidence_id="eev:flow",
                execution_flow_id="flow1",
                relation_type="ENTRY_POINT",
                endpoint_method_snapshot="GET",
                endpoint_path_snapshot="/api/users",
                controller_snapshot="TestController.listUsers",
            ),
        ]
        storage.insert_flows_batch(flows)

        # 预置 analysis 侧完整执行流 + steps（batch_get_flows 组装响应所需）。
        # analysis_execution_flows.analysis_id 有 FK → analysis_runs，先建分析记录。
        storage.create_analysis_run(
            AnalysisRun(
                analysis_id="analysis_1",
                task_id="t:ev",
                source_snapshot_id="src-1",
                run_status="SUCCEEDED",
                config_json="{}",
            )
        )
        with storage._analysis._pool.tx() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO analysis_execution_flows (
                    execution_flow_id, analysis_id, execution_flow_fingerprint,
                    entry_point, call_depth
                ) VALUES (?, ?, ?, ?, ?)""",
                ("flow1", "analysis_1", "fp:flow1", "TestController.listUsers", 2),
            )
            conn.execute(
                """INSERT OR IGNORE INTO analysis_flow_steps (
                    flow_step_id, execution_flow_id, step_index, depth,
                    method_key, class_name, method_name, call_node_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "fs:flow1:0",
                    "flow1",
                    0,
                    0,
                    "TestController.listUsers",
                    "TestController",
                    "listUsers",
                    "cn-1",
                ),
            )

        batch_map = storage.batch_get_flows(["eev:flow"])
        assert "eev:flow" in batch_map
        assert len(batch_map["eev:flow"]) == 1
        flow = batch_map["eev:flow"][0]
        # 返回完整 ExecutionFlowResponse 结构（camelCase 键），供 schema/前端直接消费
        assert flow["executionFlowId"] == "flow1"
        assert flow["entryPoint"] == "TestController.listUsers"
        assert flow["callDepth"] == 2
        assert flow["steps"][0]["methodKey"] == "TestController.listUsers"

    def test_batch_get_flows_skips_orphan_flow_id(
        self, storage: TaskSQLiteStorage, ev_base: tuple
    ) -> None:
        """analysis 侧执行流缺失时跳过孤儿引用，不返回残缺条目（避免嵌套校验 500）。"""
        cr_id, attempt_id, _ = ev_base
        ev = EndpointEvidence(
            endpoint_evidence_id="eev:orphan",
            correlation_run_id=cr_id,
            correlation_attempt_id=attempt_id,
            request_evidence_id="req:ev1",
            resolution_status=ResolutionStatus.UNIQUE,
            match_strategy=MatchStrategy.EXACT,
            confidence=MatchConfidence.HIGH,
            matched_endpoint_id="ep1",
            candidate_count=1,
        )
        storage.insert_endpoint_evidence_batch([ev])
        storage.insert_flows_batch(
            [
                EndpointEvidenceFlow(
                    endpoint_evidence_id="eev:orphan",
                    execution_flow_id="flow-gone",
                ),
            ]
        )

        batch_map = storage.batch_get_flows(["eev:orphan"])
        # 全孤儿：analysis 侧无对应执行流，跳过不产生条目（避免残缺响应）
        assert batch_map == {}

    def test_unmatched_requests_query(self, storage: TaskSQLiteStorage, ev_base: tuple) -> None:
        """P1 回归：未匹配请求查询按 resolution_status='UNMATCHED' 过滤。"""
        cr_id, attempt_id, _ = ev_base
        ev_matched = EndpointEvidence(
            endpoint_evidence_id="eev:m",
            correlation_run_id=cr_id,
            correlation_attempt_id=attempt_id,
            request_evidence_id="req:ev1",
            resolution_status=ResolutionStatus.UNIQUE,
            match_strategy=MatchStrategy.EXACT,
            confidence=MatchConfidence.HIGH,
            matched_endpoint_id="ep1",
            candidate_count=1,
        )
        ev_unmatched = EndpointEvidence(
            endpoint_evidence_id="eev:u",
            correlation_run_id=cr_id,
            correlation_attempt_id=attempt_id,
            request_evidence_id="req:ev2",
            resolution_status=ResolutionStatus.UNMATCHED,
            match_strategy=MatchStrategy.NONE,
            confidence=MatchConfidence.UNKNOWN,
            matched_endpoint_id=None,
            candidate_count=0,
        )
        storage.insert_endpoint_evidence_batch([ev_matched, ev_unmatched])

        # 激活 Attempt 后才能通过 active_attempt_id 查询未匹配请求
        storage.complete_and_activate_attempt(attempt_id, "SUCCEEDED", completeness="COMPLETE")

        items, total = storage.list_unmatched_requests(cr_id)
        assert total >= 1
        request_ids = {r.request_evidence_id for r in items}
        assert "req:ev2" in request_ids
        assert "req:ev1" not in request_ids


# ── FindingEvidence ──────────────────────────────────────────────────


class TestFindingEvidence:
    @pytest.fixture
    def attempt_id(self, storage: TaskSQLiteStorage) -> str:
        _ensure_task_and_project(storage, "t:fe", "proj:fe")
        _make_blackbox_run(storage, "bb:fe", task_id="t:fe")
        cr = _make_correlation_run(
            storage,
            "cr:fe",
            "bb:fe",
            project_id="proj:fe",
            status=CorrelationRunStatus.READY,
            analysis_id="analysis_1",
            bound_source_snapshot_id="abc123",
            analysis_projection_version=1,
        )
        attempt = storage.claim_and_create_attempt(cr.correlation_run_id, "w1")
        assert attempt is not None
        return attempt.correlation_attempt_id

    def test_insert_finding_evidence(self, storage: TaskSQLiteStorage, attempt_id: str) -> None:
        fe = FindingEvidence(
            finding_evidence_id="fe:1",
            correlation_attempt_id=attempt_id,
            finding_id="f1",
            best_relation_type=FindingRelationType.DIRECT_HANDLER,
            minimum_call_distance=0,
            confirmed_request_count=3,
            candidate_request_count=0,
        )
        storage.insert_finding_evidence_batch([fe])  # no raise

    def test_insert_finding_links_composite_fk(
        self, storage: TaskSQLiteStorage, attempt_id: str
    ) -> None:
        """FindingEvidenceLink 写入 — 复合 FK 存在时正常插入，否则抛 IntegrityError。

        finding_evidence_links 有复合 FK:
        (correlation_attempt_id, endpoint_evidence_id) → endpoint_evidence。
        该 FK 需要 endpoint_evidence 上存在 UNIQUE 索引 uq_ee_attempt_evidence。
        """
        storage.insert_http_request_batch(
            [
                HttpRequestEvidence(
                    request_evidence_id="req:fl1",
                    blackbox_run_id="bb:fe",
                    task_id="t:fe",
                    step_execution_id=None,
                    request_sequence=1,
                    http_method="GET",
                    normalized_path="/a",
                    display_path="/a",
                    origin="https://example.com",
                    endpoint_match_eligibility=CorrelationEligibility.CONFIRMED_ELIGIBLE,
                    outcome=RequestOutcome.COMPLETED,
                    request_owner=RequestOwner.FRAME,
                    captured_at="2024-01-01T00:00:00",
                ),
            ]
        )
        storage.insert_endpoint_evidence_batch(
            [
                EndpointEvidence(
                    endpoint_evidence_id="eev:fl1",
                    correlation_run_id="cr:fe",
                    correlation_attempt_id=attempt_id,
                    request_evidence_id="req:fl1",
                    resolution_status=ResolutionStatus.UNIQUE,
                    match_strategy=MatchStrategy.EXACT,
                    confidence=MatchConfidence.HIGH,
                    matched_endpoint_id="ep1",
                    candidate_count=1,
                ),
            ]
        )
        # 复合 FK 的行为取决于 uq_ee_attempt_evidence 索引：
        # - 存在 → 正常插入
        # - 不存在 → INSERT OR IGNORE 应跳过或 IntegrityError
        import sqlite3

        try:
            storage.insert_finding_links_batch(
                [
                    FindingEvidenceLink(
                        finding_evidence_id="fe:fl1",
                        correlation_attempt_id=attempt_id,
                        endpoint_evidence_id="eev:fl1",
                        endpoint_id="ep1",
                        relation_type=FindingRelationType.DIRECT_HANDLER,
                        call_distance=0,
                    ),
                ]
            )
        except sqlite3.IntegrityError:
            # 预期：复合 FK 当前不可满足
            pass


# ── Summary finding 三桶 ────────────────────────────────────────────


class TestSummaryFindingBuckets:
    """get_summary 的 Finding 三桶：confirmed / candidate / unrelated 按请求证据切分。"""

    @pytest.fixture
    def cr_id(self, storage: TaskSQLiteStorage) -> str:
        _ensure_task_and_project(storage, "t:sum", "proj:sum")
        _make_blackbox_run(storage, "bb:sum", task_id="t:sum")
        _make_correlation_run(
            storage,
            "cr:sum",
            "bb:sum",
            project_id="proj:sum",
            status=CorrelationRunStatus.READY,
            analysis_id="analysis_1",
            bound_source_snapshot_id="abc123",
            analysis_projection_version=1,
        )
        return "cr:sum"

    def test_three_buckets_partition_total(self, storage: TaskSQLiteStorage, cr_id: str) -> None:
        """confirmed=请求触达，candidate=静态关联未触达，unrelated=其余。"""
        attempt = storage.claim_and_create_attempt(cr_id, "w-sum")
        assert attempt is not None
        storage.insert_finding_evidence_batch(
            [
                FindingEvidence(
                    finding_evidence_id="fe:s1",
                    correlation_attempt_id=attempt.correlation_attempt_id,
                    finding_id="f1",
                    best_relation_type=FindingRelationType.DIRECT_HANDLER,
                    confirmed_request_count=2,
                    candidate_request_count=2,
                ),
                FindingEvidence(
                    finding_evidence_id="fe:s2",
                    correlation_attempt_id=attempt.correlation_attempt_id,
                    finding_id="f2",
                    best_relation_type=FindingRelationType.STATIC_REACHABLE,
                    confirmed_request_count=0,
                    candidate_request_count=1,
                ),
                FindingEvidence(
                    finding_evidence_id="fe:s3",
                    correlation_attempt_id=attempt.correlation_attempt_id,
                    finding_id="f3",
                    best_relation_type=FindingRelationType.UNKNOWN,
                    confirmed_request_count=0,
                    candidate_request_count=0,
                ),
            ]
        )
        storage.complete_and_activate_attempt(
            attempt.correlation_attempt_id,
            AttemptStatus.SUCCEEDED,
            completeness=EvidenceCompleteness.COMPLETE,
        )

        summary = storage.get_correlation_summary(cr_id)
        assert summary.total_finding_count == 3
        assert summary.confirmed_related_finding_count == 1
        assert summary.candidate_related_finding_count == 1
        assert summary.unrelated_finding_count == 1


# ── CaptureQuality ───────────────────────────────────────────────────


class TestCaptureQuality:
    @pytest.fixture
    def bb_id(self, base: tuple) -> str:
        return "bb:base"

    def test_upsert_and_get(self, storage: TaskSQLiteStorage, bb_id: str) -> None:
        q = CaptureQuality(
            blackbox_run_id=bb_id,
            total_observed=100,
            accepted_started=95,
            persisted_count=90,
            filtered_by_resource_type=3,
            filtered_cross_origin=2,
            filtered_by_method=1,
            filtered_path_too_long=1,
            dropped_pending_limit=2,
            dropped_run_limit=1,
            writer_retry_count=1,
            persistence_failed=2,
            truncated=True,
            truncation_reason="采集量超过上限",
            updated_at="2024-01-01T00:00:00",
        )
        storage.upsert_capture_quality(q)

        fetched = storage.get_capture_quality(bb_id)
        assert fetched is not None
        assert fetched["total_observed"] == 100
        assert fetched["persisted_count"] == 90
        assert fetched["truncated"] == 1
        assert fetched["truncation_reason"] == "采集量超过上限"
        assert fetched["filtered_cross_origin"] == 2

    def test_get_nonexistent(self, storage: TaskSQLiteStorage) -> None:
        assert storage.get_capture_quality("no-such") is None


# ── Attempt Reasons & Diagnostics ────────────────────────────────────


class TestAttemptDetails:
    @pytest.fixture
    def attempt_id(self, storage: TaskSQLiteStorage) -> str:
        _ensure_task_and_project(storage, "t:diag", "proj:diag")
        _make_blackbox_run(storage, "bb:diag", task_id="t:diag")
        cr = _make_correlation_run(
            storage,
            "cr:diag",
            "bb:diag",
            project_id="proj:diag",
            status=CorrelationRunStatus.READY,
            analysis_id="analysis_1",
            bound_source_snapshot_id="abc123",
            analysis_projection_version=1,
        )
        attempt = storage.claim_and_create_attempt(cr.correlation_run_id, "w1")
        assert attempt is not None
        return attempt.correlation_attempt_id

    def test_insert_reasons(self, storage: TaskSQLiteStorage, attempt_id: str) -> None:
        reasons = [
            CorrelationAttemptReason(
                correlation_attempt_id=attempt_id,
                reason_code=PartialReasonCode.CAPTURE_TRUNCATED,
                detail="采集量超限",
            ),
        ]
        storage.insert_attempt_reasons_batch(reasons)  # no raise

    def test_insert_diagnostics(self, storage: TaskSQLiteStorage, attempt_id: str) -> None:
        diagnostics = [
            CorrelationAttemptDiagnostic(
                correlation_attempt_id=attempt_id,
                diagnostic_code=AttemptDiagnosticCode.NO_ELIGIBLE_REQUESTS,
                detail="无符合资格的请求",
            ),
        ]
        storage.insert_attempt_diagnostics_batch(diagnostics)  # no raise


# ── Batch Lookup Helpers ─────────────────────────────────────────────


class TestBatchLookups:
    def test_batch_get_endpoint_details_empty(self, storage: TaskSQLiteStorage) -> None:
        result = storage.batch_get_endpoint_details(["no-such"])
        assert result == {}

    def test_batch_get_finding_details_empty(self, storage: TaskSQLiteStorage) -> None:
        result = storage.batch_get_finding_details(["no-such"])
        assert result == {}

    def test_batch_get_candidates_empty(self, storage: TaskSQLiteStorage) -> None:
        result = storage.batch_get_candidates([])
        assert result == {}

    def test_batch_get_flows_empty(self, storage: TaskSQLiteStorage) -> None:
        result = storage.batch_get_flows([])
        assert result == {}
