"""阶段四：关联 API 契约测试 — 通过 TestClient 走完整 HTTP 栈。

覆盖：所有 correlation 端点正常响应 + 错误状态码 +
分页边界 + display_path 可见 / normalized_path 不可见。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from argus_py.analysis.models import AnalysisRun
from argus_py.api.dependencies import (
    get_correlation_service,
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
    CorrelationRun,
    EndpointEvidence,
    EndpointEvidenceFlow,
)
from argus_py.infra.events import EventBus
from argus_py.infra.worker import TaskWorker
from argus_py.task.models import Task
from argus_py.task.storage import TaskSQLiteStorage
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers.factories import AppStack, make_app_stack
from tests.integration.correlation._fixtures import setup_request_evidence

API_PREFIX = "/argus/api"
pytestmark = [pytest.mark.integration]


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _build_correlation_test_app(tmp_path: Path) -> tuple[FastAPI, AppStack]:
    """构建包含 correlation router 的 FastAPI 应用。"""
    stack = make_app_stack(tmp_path)
    model_cfg_service = ModelConfigService(ModelConfigSQLiteStorage(tmp_path / "models.db"))
    worker = TaskWorker(
        queue=stack.queue, lifecycle=stack.lifecycle, reader=stack.reader, handlers={}
    )
    event_bus = EventBus(history_limit=50)

    app = FastAPI(title="Argus Correlation Test")
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
        get_correlation_service: lambda: stack.correlation,
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


def _seed_correlation_data(stack: AppStack) -> tuple[str, str, str]:
    """预置关联数据：project + task + blackbox_run + correlation_run + endpoint_evidence。

    返回 (correlation_run_id, attempt_id, blackbox_run_id)。
    """
    storage = stack.lifecycle.storage
    if not isinstance(storage, TaskSQLiteStorage):
        pytest.skip("Test requires SQLite storage")

    # 项目 / 任务 / BlackboxRun
    project = stack.project_service.create_project(
        name="corr-api-test", description="test", base_url="https://example.com"
    )
    task = Task(
        task_id="t-api-test",
        goal="correlation api test",
        project_id=project.project_id,
        task_type=TaskType.BLACKBOX,
        status=TaskStatus.PENDING,
    )
    storage.save(task)

    bb = storage.create_blackbox_run(
        BlackboxRun(
            blackbox_run_id="bb-api",
            task_id=task.task_id,
            attempt=1,
            status=BlackboxRunStatus.SUCCESS,
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:01:00",
        )
    )

    # CorrelationRun
    cr = storage.create_correlation_run(
        CorrelationRun(
            correlation_run_id="cr-api",
            project_id=project.project_id,
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

    # Attempt
    attempt = storage.claim_and_create_attempt(cr.correlation_run_id, "api-worker")
    assert attempt is not None

    # HttpRequestEvidence（复用共享 fixture）
    setup_request_evidence(
        storage,
        request_evidence_id="req-api-1",
        blackbox_run_id=bb.blackbox_run_id,
        task_id=task.task_id,
    )

    # EndpointEvidence
    storage.insert_endpoint_evidence_batch(
        [
            EndpointEvidence(
                endpoint_evidence_id="eev-api-1",
                correlation_run_id=cr.correlation_run_id,
                correlation_attempt_id=attempt.correlation_attempt_id,
                request_evidence_id="req-api-1",
                resolution_status=ResolutionStatus.UNIQUE,
                match_strategy=MatchStrategy.EXACT,
                confidence=MatchConfidence.HIGH,
                matched_endpoint_id="ep1",
                candidate_count=1,
                matcher_version="v1",
                normalization_version="v1",
                created_at="2024-01-01T00:00:00",
            ),
        ]
    )

    # CaptureQuality
    storage.upsert_capture_quality(
        CaptureQuality(
            blackbox_run_id=bb.blackbox_run_id,
            total_observed=50,
            persisted_count=45,
            updated_at="2024-01-01T00:00:00",
        )
    )

    # Activate
    storage.complete_and_activate_attempt(attempt.correlation_attempt_id, "SUCCEEDED", "COMPLETE")

    return cr.correlation_run_id, attempt.correlation_attempt_id, bb.blackbox_run_id


@pytest.fixture
def api_client(tmp_path: Path) -> tuple[TestClient, str, str]:
    """返回 (client, correlation_run_id, attempt_id)。"""
    app, stack = _build_correlation_test_app(tmp_path)
    cr_id, attempt_id, _ = _seed_correlation_data(stack)
    return TestClient(app), cr_id, attempt_id


_BASE = f"{API_PREFIX}/correlation-runs"


# ── GET /{cr_id} ──────────────────────────────────────────────


def test_get_correlation_run_200(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}/{cr_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlationRunId"] == cr_id
    assert data["status"] == "SUCCEEDED"


def test_get_correlation_run_404(api_client: tuple) -> None:
    client, _, _ = api_client
    resp = client.get(f"{_BASE}/no-such-cr")
    assert resp.status_code == 404


# ── GET /{cr_id}/attempts ─────────────────────────────────────


def test_list_attempts_200(api_client: tuple) -> None:
    client, cr_id, attempt_id = api_client
    resp = client.get(f"{_BASE}/{cr_id}/attempts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    returned_ids = [a["correlationAttemptId"] for a in data["items"]]
    assert attempt_id in returned_ids


def test_get_attempt_200(api_client: tuple) -> None:
    client, cr_id, attempt_id = api_client
    resp = client.get(f"{_BASE}/{cr_id}/attempts/{attempt_id}")
    assert resp.status_code == 200
    assert resp.json()["correlationAttemptId"] == attempt_id


def test_get_attempt_404(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}/{cr_id}/attempts/no-such-attempt")
    assert resp.status_code == 404


def test_get_attempt_cross_run_rejected(tmp_path: Path) -> None:
    """P1 回归：Run A 的 URL 访问 Run B 的 attempt_id → 404。"""
    app, stack = _build_correlation_test_app(tmp_path)
    storage = stack.lifecycle.storage
    assert isinstance(storage, TaskSQLiteStorage)

    # 基础数据：project + task + blackbox_run
    project = stack.project_service.create_project(
        name="corr-api-cross", description="test", base_url="https://example.com"
    )
    task = Task(
        task_id="t-cross",
        goal="cross-run test",
        project_id=project.project_id,
        task_type=TaskType.BLACKBOX,
        status=TaskStatus.PENDING,
    )
    storage.save(task)

    bb = storage.create_blackbox_run(
        BlackboxRun(
            blackbox_run_id="bb-cross",
            task_id=task.task_id,
            attempt=1,
            status=BlackboxRunStatus.SUCCESS,
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:01:00",
        )
    )

    # 创建 Run A + Attempt A
    storage.create_correlation_run(
        CorrelationRun(
            correlation_run_id="cr-a",
            project_id=project.project_id,
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
    attempt_a = storage.claim_and_create_attempt("cr-a", "w1")
    assert attempt_a is not None

    # 创建 Run B + Attempt B
    storage.create_correlation_run(
        CorrelationRun(
            correlation_run_id="cr-b",
            project_id=project.project_id,
            blackbox_run_id=bb.blackbox_run_id,
            desired_source_snapshot_id="xyz789",
            correlation_config_digest="d2",
            matcher_version="v1",
            normalization_version="v1",
            analysis_id="analysis-2",
            bound_source_snapshot_id="xyz789",
            analysis_projection_version=2,
            status=CorrelationRunStatus.READY,
            created_at="2024-01-01T00:00:00",
        )
    )
    attempt_b = storage.claim_and_create_attempt("cr-b", "w2")
    assert attempt_b is not None

    client = TestClient(app)

    # 用 Run A 的 URL 访问 Run B 的 attempt → 404
    resp = client.get(f"{_BASE}/cr-a/attempts/{attempt_b.correlation_attempt_id}")
    assert resp.status_code == 404

    # 用 Run B 的 URL 访问 Run B 的 attempt → 200
    resp = client.get(f"{_BASE}/cr-b/attempts/{attempt_b.correlation_attempt_id}")
    assert resp.status_code == 200
    assert resp.json()["correlationAttemptId"] == attempt_b.correlation_attempt_id


# ── GET /{cr_id}/summary ──────────────────────────────────────


def test_summary_200(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}/{cr_id}/summary")
    assert resp.status_code == 200
    data = resp.json()
    # 核心标识
    assert data["correlationRunId"] == cr_id
    assert data["status"] == "SUCCEEDED"
    assert isinstance(data["matcherVersion"], str)
    assert isinstance(data["normalizationVersion"], str)
    # 请求级指标
    assert data["capturedRequestCount"] >= 1
    assert isinstance(data["correlatableRequestCount"], int)
    assert isinstance(data["confirmedMatchedRequestCount"], int)
    assert isinstance(data["unmatchedRequestCount"], int)
    # 证据完备性
    assert data["evidenceCompleteness"] in ("COMPLETE", "PARTIAL")


# ── GET /{cr_id}/endpoint-evidence ───────────────────────────


def test_list_endpoint_evidence_200(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}/{cr_id}/endpoint-evidence")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    # 关联执行流必须以 camelCase executionFlows 键序列化（回归：旧版缺失 alias）
    for item in data["items"]:
        assert "executionFlows" in item, f"Expected executionFlows key, got: {sorted(item.keys())}"
        assert "execution_flows" not in item


def test_endpoint_evidence_response_includes_execution_flows(tmp_path: Path) -> None:
    """回归：端点证据 API 必须把关联执行流序列化为完整 ExecutionFlowResponse
    （executionFlows 键 + entryPoint/callDepth/steps），否则前端「调用流」列恒为空。"""
    app, stack = _build_correlation_test_app(tmp_path)
    storage = stack.lifecycle.storage
    assert isinstance(storage, TaskSQLiteStorage)
    cr_id, _, _ = _seed_correlation_data(stack)

    # analysis 侧完整执行流 + steps（analysis_id 对应 seed 的 analysis-1）
    storage.create_analysis_run(
        AnalysisRun(
            analysis_id="analysis-1",
            task_id="t-api-test",
            source_snapshot_id="src-api",
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
            ("flow-api-1", "analysis-1", "fp:api", "UserController.listUsers", 2),
        )
        conn.execute(
            """INSERT OR IGNORE INTO analysis_flow_steps (
                flow_step_id, execution_flow_id, step_index, depth,
                method_key, class_name, method_name, call_node_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "fs-api-1",
                "flow-api-1",
                0,
                0,
                "UserController.listUsers",
                "UserController",
                "listUsers",
                "cn-1",
            ),
        )

    # 证据 ↔ 执行流关联
    storage.insert_flows_batch(
        [
            EndpointEvidenceFlow(
                endpoint_evidence_id="eev-api-1",
                execution_flow_id="flow-api-1",
                relation_type="ENTRY_POINT",
            ),
        ]
    )

    client = TestClient(app)
    resp = client.get(f"{_BASE}/{cr_id}/endpoint-evidence?limit=1")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert items, "expected seeded endpoint evidence"
    item = next((i for i in items if i["endpointEvidenceId"] == "eev-api-1"), None)
    assert item is not None, f"expected eev-api-1, got: {[i['endpointEvidenceId'] for i in items]}"
    flows = item["executionFlows"]
    assert len(flows) == 1
    assert flows[0]["executionFlowId"] == "flow-api-1"
    assert flows[0]["entryPoint"] == "UserController.listUsers"
    assert flows[0]["callDepth"] == 2
    assert flows[0]["steps"][0]["methodKey"] == "UserController.listUsers"
    assert "execution_flows" not in item


def test_list_endpoint_evidence_filter_by_status(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}/{cr_id}/endpoint-evidence?resolutionStatus=UNIQUE")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["resolutionStatus"] == "UNIQUE"


def test_list_endpoint_evidence_pagination(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}/{cr_id}/endpoint-evidence?limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) <= 1


# ── GET /{cr_id}/unmatched-requests ──────────────────────────


def test_list_unmatched_requests_200(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}/{cr_id}/unmatched-requests")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int)
    assert isinstance(data["hasMore"], bool)
    # 请求证据 不 暴露 normalizedPath（敏感字段）
    if data["items"]:
        item0 = data["items"][0]
        assert "displayPath" in item0, f"Expected displayPath, got keys: {sorted(item0.keys())}"
        assert "normalizedPath" not in item0, (
            "Sensitive field 'normalizedPath' should not be exposed"
        )


# ── GET /{cr_id}/finding-evidence ────────────────────────────


def test_list_finding_evidence_200(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}/{cr_id}/finding-evidence")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int)
    assert isinstance(data["hasMore"], bool)
    # 有数据时校验 Finding 证据结构
    if data["items"]:
        fe = data["items"][0]
        assert "findingEvidenceId" in fe
        assert "findingId" in fe
        assert "bestRelationType" in fe
        assert "confirmedRequestCount" in fe


# ── GET /{cr_id}/capture-quality ─────────────────────────────


def test_capture_quality_200(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}/{cr_id}/capture-quality")
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalObserved"] == 50


# ── GET /{cr_id}/uncovered-endpoints ─────────────────────────


def test_uncovered_endpoints_200(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}/{cr_id}/uncovered-endpoints")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int)
    assert isinstance(data["hasMore"], bool)
    # 有数据时校验未触达端点结构
    if data["items"]:
        ep = data["items"][0]
        assert "endpointId" in ep
        assert "httpMethod" in ep
        assert "normalizedPathTemplate" in ep


# ── GET ?taskId= ─────────────────────────────────────────────


def test_list_by_task_200(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}?taskId=t-api-test")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    returned_ids = [r["correlationRunId"] for r in data]
    assert cr_id in returned_ids


def test_list_by_task_empty(api_client: tuple) -> None:
    client, _, _ = api_client
    resp = client.get(f"{_BASE}?taskId=no-such-task")
    assert resp.status_code == 200
    assert resp.json() == []


# ── POST /{cr_id}/bind-analysis ──────────────────────────────


def test_bind_analysis_409_no_analysis_id(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.post(
        f"{_BASE}/{cr_id}/bind-analysis",
        json={"analysisId": "", "expectedProjectionVersion": 1},
    )
    # 空 analysisId 应返回 409（BIND_FAILED）或 422（validation）
    assert resp.status_code in (409, 422)


# ── POST /{cr_id}/retry ──────────────────────────────────────


def test_retry_409_when_succeeded(api_client: tuple) -> None:
    """SUCCEEDED 状态重试 → 409。"""
    client, cr_id, _ = api_client
    resp = client.post(f"{_BASE}/{cr_id}/retry")
    assert resp.status_code == 409


# ── POST /{cr_id}/recalculate ────────────────────────────────


def test_recalculate_201(api_client: tuple) -> None:
    client, cr_id, _ = api_client
    resp = client.post(f"{_BASE}/{cr_id}/recalculate")
    assert resp.status_code == 201
    data = resp.json()
    assert "correlationRunId" in data


# ── display_path 可见 / 敏感字段不暴露 ──────────────────


def test_endpoint_evidence_response_has_display_path(api_client: tuple) -> None:
    """端点证据 API 必须返回 displayPath，且不暴露 normalizedPath 等敏感字段。"""
    client, cr_id, _ = api_client
    resp = client.get(f"{_BASE}/{cr_id}/endpoint-evidence?limit=1")
    assert resp.status_code == 200
    items = resp.json()["items"]
    if not items:
        pytest.skip("No endpoint evidence available")
    item = items[0]
    # 核心标识
    assert "endpointEvidenceId" in item, f"Expected camelCase keys, got: {sorted(item.keys())}"
    assert "resolutionStatus" in item
    assert "matchStrategy" in item
    assert "confidence" in item
    # displayPath 可见
    assert "displayPath" in item, (
        f"Expected displayPath in response, got keys: {sorted(item.keys())}"
    )
    assert isinstance(item["displayPath"], str), (
        f"displayPath should be a string, got {type(item['displayPath']).__name__}"
    )
    assert len(item["displayPath"]) > 0, (
        f"displayPath must be non-empty, got {item['displayPath']!r}"
    )
    # 敏感字段 不 返回
    SENSITIVE_KEYS = {"normalizedPath"}
    for key in SENSITIVE_KEYS:
        assert key not in item, f"Sensitive field '{key}' should not be exposed in API response"


# ── OpenAPI schema 包含 correlation routes ───────────────────


def test_openapi_contains_correlation_paths(api_client: tuple) -> None:
    client, _, _ = api_client
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    paths = list(schema.get("paths", {}).keys())
    correlation_paths = [p for p in paths if "correlation" in p.lower()]
    assert len(correlation_paths) > 0, (
        f"No correlation paths in OpenAPI schema, got: {sorted(paths)}"
    )
