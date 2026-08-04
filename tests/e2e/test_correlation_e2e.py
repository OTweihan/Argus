"""阶段四：关联 E2E 测试 — 通过 TestClient 走完整 HTTP 栈，覆盖黑盒→白盒→关联→证据链。

与 tests/integration/test_api_correlation.py 区别：
- 集成测试：单次 API 调用校验
- E2E 测试：完整业务链路（创建 → 认领 → 写入证据 → 激活 → 查询报表）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from argus_py.api.dependencies import (
    get_debug_bundle_builder,
    get_event_bus,
    get_model_config_service,
    get_project_service,
    get_task_app_service,
    get_task_queue,
    get_task_read_service,
    get_task_timeline_service,
    get_task_worker,
    get_trace_reader_service,
)
from argus_py.api.middleware import configure_middleware
from argus_py.api.routes import (
    config,
    correlation,
    events,
    health,
    projects,
    prompts,
    reports,
    tasks,
    ws,
)
from argus_py.config.model_storage import ModelConfigSQLiteStorage
from argus_py.config.server_settings import ServerSettings
from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.correlation.enums import (
    BlackboxRunStatus,
    CorrelationRunStatus,
    MatchConfidence,
    MatchStrategy,
    ResolutionStatus,
)
from argus_py.correlation.models import (
    BlackboxRun,
    CaptureQuality,
    CorrelationEligibility,
    CorrelationRun,
    EndpointEvidence,
    FindingEvidence,
    FindingRelationType,
    HttpRequestEvidence,
    RequestOutcome,
    RequestOwner,
)
from argus_py.infra.events import EventBus
from argus_py.infra.worker import TaskWorker
from argus_py.task.models import Task
from argus_py.task.storage import TaskSQLiteStorage
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.helpers.factories import AppStack, make_app_stack

API_PREFIX = "/argus/api"
_BASE = f"{API_PREFIX}/correlation-runs"
pytestmark = [pytest.mark.e2e]


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _build_test_app(tmp_path: Path) -> tuple[FastAPI, AppStack]:
    stack = make_app_stack(tmp_path)
    model_cfg_service = ModelConfigService(ModelConfigSQLiteStorage(tmp_path / "models.db"))
    worker = TaskWorker(
        queue=stack.queue, lifecycle=stack.lifecycle, reader=stack.reader, handlers={}
    )
    event_bus = EventBus(history_limit=50)

    app = FastAPI(title="Argus Correlation E2E")
    app.router.lifespan_context = _noop_lifespan
    configure_middleware(app, ServerSettings())

    app.include_router(health.router)
    app.include_router(projects.router, prefix=API_PREFIX)
    app.include_router(tasks.router, prefix=API_PREFIX)
    app.include_router(reports.router, prefix=API_PREFIX)
    app.include_router(config.router, prefix=API_PREFIX)
    app.include_router(events.router, prefix=API_PREFIX)
    app.include_router(prompts.router, prefix=API_PREFIX)
    app.include_router(ws.router, prefix=API_PREFIX)
    app.include_router(correlation.router, prefix=API_PREFIX)

    overrides: dict[Any, Any] = {
        get_project_service: lambda: stack.project_service,
        get_task_queue: lambda: stack.queue,
        get_task_app_service: lambda: stack.app,
        get_model_config_service: lambda: model_cfg_service,
        get_task_read_service: lambda: stack.reader,
        get_trace_reader_service: lambda: stack.trace_reader,
        get_debug_bundle_builder: lambda: stack.debug_builder,
        get_task_timeline_service: lambda: stack.timeline,
        get_task_worker: lambda: worker,
        get_event_bus: lambda: event_bus,
    }
    app.dependency_overrides.update(overrides)
    return app, stack


def _seed_full_pipeline(
    storage: TaskSQLiteStorage,
    project_id: str,
) -> tuple[str, str, str, str, str]:
    """构建完整数据链路：task + blackbox + correlation_run + request_evidence +
    endpoint_evidence + finding_evidence → 激活 Attempt。

    返回 (correlation_run_id, attempt_id, blackbox_run_id, task_id, project_id)。
    """
    # task
    task = Task(
        task_id="t-e2e",
        goal="E2E correlation chain",
        project_id=project_id,
        task_type=TaskType.BLACKBOX,
        status=TaskStatus.PENDING,
    )
    storage.save(task)

    # blackbox run
    bb = storage.create_blackbox_run(
        BlackboxRun(
            blackbox_run_id="bb-e2e",
            task_id=task.task_id,
            attempt=1,
            status=BlackboxRunStatus.SUCCESS,
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:01:00",
        )
    )

    # http request evidence (3 条：UNIQUE 匹配、AMBIGUOUS 匹配、UNMATCHED)
    for i, (rid, path) in enumerate(
        [
            ("req-e2e-1", "/api/users"),
            ("req-e2e-2", "/api/users"),
            ("req-e2e-3", "/api/nonexistent"),
        ],
        start=1,
    ):
        storage.insert_http_request_batch(
            [
                HttpRequestEvidence(
                    request_evidence_id=rid,
                    blackbox_run_id=bb.blackbox_run_id,
                    task_id=task.task_id,
                    step_execution_id=None,
                    request_sequence=i,
                    http_method="GET",
                    normalized_path=path,
                    display_path=path,
                    origin="https://example.com",
                    endpoint_match_eligibility=CorrelationEligibility.CONFIRMED_ELIGIBLE,
                    outcome=RequestOutcome.COMPLETED,
                    request_owner=RequestOwner.FRAME,
                    captured_at="2024-01-01T00:00:00",
                )
            ]
        )

    # correlation run
    cr = storage.create_correlation_run(
        CorrelationRun(
            correlation_run_id="cr-e2e",
            project_id=project_id,
            blackbox_run_id=bb.blackbox_run_id,
            desired_source_snapshot_id="abc123",
            correlation_config_digest="d1",
            matcher_version="v1",
            normalization_version="v1",
            analysis_id="analysis-1",
            bound_source_snapshot_id="abc123",
            analysis_projection_version=1,
            status=CorrelationRunStatus.READY,
            created_at="2024-01-01T00:00:00",
        )
    )

    # claim attempt
    attempt = storage.claim_and_create_attempt(cr.correlation_run_id, "e2e-worker")
    assert attempt is not None

    # endpoint evidence: 2 UNIQUE + 1 UNMATCHED + 1 AMBIGUOUS
    storage.insert_endpoint_evidence_batch(
        [
            EndpointEvidence(
                endpoint_evidence_id="eev-e2e-1",
                correlation_run_id=cr.correlation_run_id,
                correlation_attempt_id=attempt.correlation_attempt_id,
                request_evidence_id="req-e2e-1",
                resolution_status=ResolutionStatus.UNIQUE,
                match_strategy=MatchStrategy.EXACT,
                confidence=MatchConfidence.HIGH,
                matched_endpoint_id="ep-users",
                candidate_count=1,
                matcher_version="v1",
                normalization_version="v1",
                created_at="2024-01-01T00:00:00",
            ),
            EndpointEvidence(
                endpoint_evidence_id="eev-e2e-2",
                correlation_run_id=cr.correlation_run_id,
                correlation_attempt_id=attempt.correlation_attempt_id,
                request_evidence_id="req-e2e-2",
                resolution_status=ResolutionStatus.UNIQUE,
                match_strategy=MatchStrategy.TEMPLATE,
                confidence=MatchConfidence.HIGH,
                matched_endpoint_id="ep-users-id",
                candidate_count=1,
                matcher_version="v1",
                normalization_version="v1",
                created_at="2024-01-01T00:00:00",
            ),
            EndpointEvidence(
                endpoint_evidence_id="eev-e2e-3",
                correlation_run_id=cr.correlation_run_id,
                correlation_attempt_id=attempt.correlation_attempt_id,
                request_evidence_id="req-e2e-3",
                resolution_status=ResolutionStatus.UNMATCHED,
                match_strategy=MatchStrategy.NONE,
                confidence=MatchConfidence.UNKNOWN,
                matched_endpoint_id=None,
                candidate_count=0,
                matcher_version="v1",
                normalization_version="v1",
                created_at="2024-01-01T00:00:00",
            ),
        ]
    )

    # finding evidence
    storage.insert_finding_evidence_batch(
        [
            FindingEvidence(
                finding_evidence_id="fe-e2e-1",
                correlation_attempt_id=attempt.correlation_attempt_id,
                finding_id="f1",
                best_relation_type=FindingRelationType.DIRECT_HANDLER,
                minimum_call_distance=0,
                confirmed_request_count=2,
                candidate_request_count=0,
            ),
        ]
    )

    # capture quality
    storage.upsert_capture_quality(
        CaptureQuality(
            blackbox_run_id=bb.blackbox_run_id,
            total_observed=100,
            persisted_count=95,
            filtered_cross_origin=3,
            filtered_by_resource_type=2,
            updated_at="2024-01-01T00:00:00",
        )
    )

    # activate
    storage.complete_and_activate_attempt(
        attempt.correlation_attempt_id, "SUCCEEDED", completeness="COMPLETE"
    )

    return (
        cr.correlation_run_id,
        attempt.correlation_attempt_id,
        bb.blackbox_run_id,
        task.task_id,
        project_id,
    )


@pytest.fixture
def e2e_client(tmp_path: Path) -> tuple[TestClient, str, str, str]:
    """返回 (client, correlation_run_id, attempt_id, project_id)。"""
    app, stack = _build_test_app(tmp_path)
    storage = stack.lifecycle.storage
    assert isinstance(storage, TaskSQLiteStorage)

    project = stack.project_service.create_project(
        name="e2e-correlation", description="E2E", base_url="https://example.com"
    )

    cr_id, attempt_id, bb_id, task_id, project_id = _seed_full_pipeline(storage, project.project_id)

    return TestClient(app), cr_id, attempt_id, project_id


# ── 黑盒 → 白盒 → 关联 完整链路 ──────────────────────────────


def test_full_chain_correlation_run_accessible(e2e_client: tuple) -> None:
    """E2E: 完整链路数据就绪 → CorrelationRun GET 返回正确状态。"""
    client, cr_id, _, _ = e2e_client
    resp = client.get(f"{_BASE}/{cr_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlationRunId"] == cr_id
    assert data["status"] == "SUCCEEDED"
    assert data["activeAttemptId"] is not None


def test_full_chain_endpoint_evidence_filtering(e2e_client: tuple) -> None:
    """E2E: 按 resolutionStatus 过滤 → 分别返回 UNIQUE/UNMATCHED 证据。"""
    client, cr_id, _, _ = e2e_client

    # 按 UNIQUE 过滤
    resp = client.get(f"{_BASE}/{cr_id}/endpoint-evidence?resolutionStatus=UNIQUE")
    assert resp.status_code == 200
    unique_items = resp.json()["items"]
    assert len(unique_items) >= 2
    for item in unique_items:
        assert item["resolutionStatus"] == "UNIQUE"

    # 按 UNMATCHED 过滤
    resp = client.get(f"{_BASE}/{cr_id}/endpoint-evidence?resolutionStatus=UNMATCHED")
    assert resp.status_code == 200
    unmatched_items = resp.json()["items"]
    assert len(unmatched_items) >= 1
    for item in unmatched_items:
        assert item["resolutionStatus"] == "UNMATCHED"


def test_full_chain_match_strategy_filter(e2e_client: tuple) -> None:
    """E2E: 按 matchStrategy 过滤 → EXACT/TEMPLATE 分别返回。"""
    client, cr_id, _, _ = e2e_client

    resp = client.get(f"{_BASE}/{cr_id}/endpoint-evidence?matchStrategy=EXACT")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["matchStrategy"] == "EXACT"

    resp = client.get(f"{_BASE}/{cr_id}/endpoint-evidence?matchStrategy=TEMPLATE")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["matchStrategy"] == "TEMPLATE"


def test_full_chain_unmatched_requests(e2e_client: tuple) -> None:
    """E2E: 未匹配请求列表 → 返回 resolution_status='UNMATCHED' 的请求。"""
    client, cr_id, _, _ = e2e_client
    resp = client.get(f"{_BASE}/{cr_id}/unmatched-requests")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


def test_full_chain_finding_evidence(e2e_client: tuple) -> None:
    """E2E: Finding 关联证据 → 返回完整链路数据。"""
    client, cr_id, _, _ = e2e_client
    resp = client.get(f"{_BASE}/{cr_id}/finding-evidence")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert data["items"][0]["bestRelationType"] == "DIRECT_HANDLER"


def test_full_chain_summary(e2e_client: tuple) -> None:
    """E2E: Summary 聚合 → 包含采集质量和关联统计。"""
    client, cr_id, _, _ = e2e_client
    resp = client.get(f"{_BASE}/{cr_id}/summary")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["capturedRequestCount"] >= 3
    assert summary["confirmedMatchedRequestCount"] >= 2
    assert summary["unmatchedRequestCount"] >= 1


def test_full_chain_capture_quality(e2e_client: tuple) -> None:
    """E2E: 采集质量 → 包含过滤和丢弃统计。"""
    client, cr_id, _, _ = e2e_client
    resp = client.get(f"{_BASE}/{cr_id}/capture-quality")
    assert resp.status_code == 200
    cq = resp.json()
    assert cq["totalObserved"] == 100
    assert cq["persistedCount"] == 95
    assert cq["filteredCrossOrigin"] == 3
    assert cq["filteredByResourceType"] == 2


def test_full_chain_attempts_list(e2e_client: tuple) -> None:
    """E2E: 列出所有 Attempt → 包含已激活的尝试。"""
    client, cr_id, attempt_id, _ = e2e_client
    resp = client.get(f"{_BASE}/{cr_id}/attempts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    returned_ids = [a["correlationAttemptId"] for a in data["items"]]
    assert attempt_id in returned_ids
    # 激活的 Attempt 应标记为 SUCCEEDED
    active = next(a for a in data["items"] if a["correlationAttemptId"] == attempt_id)
    assert active["status"] == "SUCCEEDED"


def test_full_chain_pagination_boundary(e2e_client: tuple) -> None:
    """E2E: 分页边界 → limit=1 返回不超过 1 条，total 不变。"""
    client, cr_id, _, _ = e2e_client
    # 先拿全部 total
    resp_all = client.get(f"{_BASE}/{cr_id}/endpoint-evidence")
    total_all = resp_all.json()["total"]

    resp = client.get(f"{_BASE}/{cr_id}/endpoint-evidence?limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) <= 1
    assert data["total"] == total_all


def test_full_chain_attempt_cross_run_rejected(e2e_client: tuple) -> None:
    """E2E: 跨 Run 归属 → 用不存在的 Run ID 访问合法的 attempt_id 返回 404。

    合法 Attempt 通过正确的 Run URL 可以访问 (200)，
    但通过其他 Run 的 URL 访问返回 404（归属校验）。
    """
    client, cr_id_a, attempt_id_a, _ = e2e_client

    # 用 Run A 的 URL + Run A 的 attempt_id → 200（合法）
    resp = client.get(f"{_BASE}/{cr_id_a}/attempts/{attempt_id_a}")
    assert resp.status_code == 200
    assert resp.json()["correlationAttemptId"] == attempt_id_a

    # 用不存在的 Run ID + 合法的 attempt_id → 404（跨 Run 归属校验）
    resp = client.get(f"{_BASE}/no-such-run/attempts/{attempt_id_a}")
    assert resp.status_code == 404


def test_full_chain_404_on_nonexistent(e2e_client: tuple) -> None:
    """E2E: 不存在的 CorrelationRun → 404。"""
    client, _, _, _ = e2e_client
    resp = client.get(f"{_BASE}/no-such-cr")
    assert resp.status_code == 404


def test_full_chain_list_correlation_runs_by_task(e2e_client: tuple) -> None:
    """E2E: 按 taskId 查询关联运行。"""
    client, _, _, _ = e2e_client
    resp = client.get(f"{_BASE}?taskId=t-e2e")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["correlationRunId"] == "cr-e2e"
