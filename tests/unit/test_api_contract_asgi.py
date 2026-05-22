"""ASGI 层契约测试：通过 TestClient 走完整中间件链验证 HTTP 响应。

与 ``tests/unit/test_route_contracts.py``（直接调用 handler）互补：
- 本文件经过 JSON 序列化、中间件、异常处理 handler
- handler 级测试覆盖细粒度业务状态码与错误码

不启动基础设施（worker / lifespan），服务层通过 ``dependency_overrides`` 注入。
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
    get_task_query_service,
    get_task_queue,
    get_task_read_service,
    get_task_timeline_service,
    get_task_worker,
    get_trace_reader_service,
)
from argus_py.api.middleware import configure_middleware
from argus_py.api.routes import config, events, health, projects, prompts, reports, tasks, ws
from argus_py.config.model_storage import ModelConfigSQLiteStorage
from argus_py.config.server_settings import ServerSettings
from argus_py.config.service import ModelConfigService
from argus_py.infra.events import EventBus
from argus_py.infra.worker import TaskWorker
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers.factories import AppStack, make_app_stack

API_PREFIX = "/api/v1"
pytestmark = [pytest.mark.integration]


# ── Test app factory ───────────────────────────────────────────────────────────


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """不启动 worker / DB recovery 的零开销 lifespan。"""
    yield


def _build_test_app(tmp_path: Path) -> tuple[FastAPI, AppStack]:
    """构建带测试服务栈的 FastAPI 应用。

    Route 注册与 ``create_app()`` 保持一致，但跳过 lifespan；
    全部路由依赖被 override 为测试实例。
    """
    stack = make_app_stack(tmp_path)
    model_cfg_service = ModelConfigService(ModelConfigSQLiteStorage(tmp_path / "models.db"))
    worker = TaskWorker(queue=stack.queue, lifecycle=stack.lifecycle, reader=stack.reader)
    event_bus = EventBus(history_limit=50)

    app = FastAPI(title="Argus API Test")
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

    overrides: dict[Any, Any] = {
        get_project_service: lambda: stack.project_service,
        get_task_queue: lambda: stack.queue,
        get_task_app_service: lambda: stack.app,
        get_model_config_service: lambda: model_cfg_service,
        get_task_query_service: lambda: stack.query,
        get_task_read_service: lambda: stack.reader,
        get_trace_reader_service: lambda: stack.trace_reader,
        get_debug_bundle_builder: lambda: stack.debug_builder,
        get_task_timeline_service: lambda: stack.timeline,
        get_task_worker: lambda: worker,
        get_event_bus: lambda: event_bus,
    }
    app.dependency_overrides.update(overrides)

    return app, stack


@pytest.fixture
def _app(tmp_path: Path) -> FastAPI:
    app, _ = _build_test_app(tmp_path)
    return app


@pytest.fixture
def client(_app: FastAPI) -> TestClient:
    return TestClient(_app)


# ── OpenAPI schema 契约 ───────────────────────────────────────────────────────


class TestOpenAPISchema:
    """OpenAPI JSON schema 结构契约。"""

    def test_openapi_json_is_served(self, client: TestClient) -> None:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")

    def test_openapi_contains_all_routes(self, client: TestClient) -> None:
        resp = client.get("/openapi.json")
        spec = resp.json()
        paths = spec["paths"]
        assert "/health" in paths
        assert f"{API_PREFIX}/projects" in paths
        assert f"{API_PREFIX}/tasks" in paths
        assert f"{API_PREFIX}/tasks/{{task_id}}/start" in paths

    def test_task_create_has_request_body(self, client: TestClient) -> None:
        resp = client.get("/openapi.json")
        post_tasks = resp.json()["paths"][f"{API_PREFIX}/tasks"]["post"]
        assert "requestBody" in post_tasks


# ── Health ─────────────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    """/health /ready /metrics 的 HTTP 契约。"""

    def test_health_returns_200(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")

    def test_health_body_shape(self, client: TestClient) -> None:
        resp = client.get("/health")
        body = resp.json()
        assert body["status"] == "healthy"
        assert isinstance(body["version"], str)
        assert isinstance(body["project"], str)

    def test_ready_returns_not_ready(self, client: TestClient) -> None:
        """Worker 未启动时 status 应为 not_ready。"""
        resp = client.get("/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "not_ready"
        assert "db" in body
        assert "worker" in body
        assert "event_bus" in body

    def test_metrics_returns_200(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_tasks" in body
        assert "running_tasks" in body
        assert isinstance(body["total_tasks"], int)


# ── Projects ───────────────────────────────────────────────────────────────────


class TestProjectContract:
    """项目 CRUD 的 HTTP 契约。"""

    def test_list_projects_empty(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/projects")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["projects"] == []

    def test_create_project_201(self, client: TestClient) -> None:
        resp = client.post(
            f"{API_PREFIX}/projects",
            json={"name": "契约测试", "baseUrl": "https://example.com"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "projectId" in body
        assert body["name"] == "契约测试"

    def test_create_project_missing_name_422(self, client: TestClient) -> None:
        resp = client.post(f"{API_PREFIX}/projects", json={"baseUrl": "https://example.com"})
        assert resp.status_code == 422
        err = resp.json()
        assert err["error"]["code"] == "INVALID_REQUEST"
        assert "details" in err["error"]

    def test_get_project_404_shape(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/projects/no-such")
        assert resp.status_code == 404
        err = resp.json()
        assert err["error"]["code"] == "PROJECT_NOT_FOUND"
        assert isinstance(err["error"]["message"], str)
        assert isinstance(err["error"]["details"], dict)

    def test_create_and_get_project(self, client: TestClient) -> None:
        created = client.post(
            f"{API_PREFIX}/projects",
            json={"name": "查询测试", "baseUrl": "https://example.com"},
        )
        pid = created.json()["projectId"]

        resp = client.get(f"{API_PREFIX}/projects/{pid}")
        assert resp.status_code == 200
        assert resp.json()["projectId"] == pid

    def test_create_and_delete_project(self, client: TestClient) -> None:
        created = client.post(
            f"{API_PREFIX}/projects",
            json={"name": "删除测试", "baseUrl": "https://example.com"},
        )
        pid = created.json()["projectId"]

        resp = client.delete(f"{API_PREFIX}/projects/{pid}")
        assert resp.status_code == 204

        resp = client.get(f"{API_PREFIX}/projects/{pid}")
        assert resp.status_code == 404


# ── Tasks ──────────────────────────────────────────────────────────────────────


class TestTaskContract:
    """任务 CRUD + 状态机操作的 HTTP 契约。"""

    def _create_project(self, client: TestClient) -> str:
        resp = client.post(
            f"{API_PREFIX}/projects",
            json={"name": "任务项目", "baseUrl": "https://example.com"},
        )
        return resp.json()["projectId"]

    def test_list_tasks_empty(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/tasks")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["tasks"] == []

    def test_create_task_201(self, client: TestClient) -> None:
        pid = self._create_project(client)
        resp = client.post(
            f"{API_PREFIX}/tasks",
            json={"projectId": pid, "goal": "打开首页", "startUrl": "https://example.com"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "taskId" in body
        assert body["status"] == "pending"

    def test_create_task_missing_goal_422(self, client: TestClient) -> None:
        pid = self._create_project(client)
        resp = client.post(
            f"{API_PREFIX}/tasks",
            json={"projectId": pid, "startUrl": "https://example.com"},
        )
        assert resp.status_code == 422

    def test_get_task_404_shape(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/tasks/task-00000000000000-deadbeef")
        assert resp.status_code == 404
        err = resp.json()
        assert err["error"]["code"] == "TASK_NOT_FOUND"

    def test_create_and_get_task(self, client: TestClient) -> None:
        pid = self._create_project(client)
        created = client.post(
            f"{API_PREFIX}/tasks",
            json={"projectId": pid, "goal": "E2E 验证首页", "startUrl": "https://example.com"},
        )
        tid = created.json()["taskId"]

        resp = client.get(f"{API_PREFIX}/tasks/{tid}")
        assert resp.status_code == 200
        assert resp.json()["taskId"] == tid

    def test_infer_limits(self, client: TestClient) -> None:
        resp = client.get(
            f"{API_PREFIX}/tasks/infer-limits",
            params={"goal": "打开首页"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["maxSteps"] > 0
        assert body["timeoutSeconds"] > 0

    def test_start_task_returns_queued(self, client: TestClient) -> None:
        pid = self._create_project(client)
        created = client.post(
            f"{API_PREFIX}/tasks",
            json={"projectId": pid, "goal": "可启动任务", "startUrl": "https://example.com"},
        )
        tid = created.json()["taskId"]

        resp = client.post(f"{API_PREFIX}/tasks/{tid}/start")
        assert resp.status_code == 200
        assert resp.json()["schedulerStatus"] == "queued"

    def test_restart_fails_on_pending(self, client: TestClient) -> None:
        """pending 任务不允许 restart → 409。"""
        pid = self._create_project(client)
        created = client.post(
            f"{API_PREFIX}/tasks",
            json={"projectId": pid, "goal": "不可以 restart", "startUrl": "https://example.com"},
        )
        tid = created.json()["taskId"]

        resp = client.post(f"{API_PREFIX}/tasks/{tid}/restart")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "TASK_NOT_RETRYABLE"

    def test_cancel_pending_returns_cancelled(self, client: TestClient) -> None:
        pid = self._create_project(client)
        created = client.post(
            f"{API_PREFIX}/tasks",
            json={"projectId": pid, "goal": "取消 pending", "startUrl": "https://example.com"},
        )
        tid = created.json()["taskId"]

        resp = client.post(f"{API_PREFIX}/tasks/{tid}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"


# ── Error response format ─────────────────────────────────────────────────────


class TestErrorResponseFormat:
    """统一错误响应格式 ``{error: {code, message, details}}`` 的契约。"""

    def test_404_error_shape(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/projects/no-such")
        err = resp.json()["error"]
        assert set(err) == {"code", "message", "details"}
        assert isinstance(err["details"], dict)

    def test_422_error_shape(self, client: TestClient) -> None:
        resp = client.post(f"{API_PREFIX}/projects", json={})
        err = resp.json()["error"]
        assert err["code"] == "INVALID_REQUEST"
        assert "details" in err

    def test_409_error_shape(self, client: TestClient) -> None:
        pid = self._create_project(client)
        tid = self._create_task(client, pid)
        resp = client.post(f"{API_PREFIX}/tasks/{tid}/restart")
        err = resp.json()["error"]
        assert err["code"] == "TASK_NOT_RETRYABLE"
        assert isinstance(err["message"], str)

    def _create_project(self, client: TestClient) -> str:
        resp = client.post(
            f"{API_PREFIX}/projects",
            json={"name": "错误测试项目", "baseUrl": "https://example.com"},
        )
        return resp.json()["projectId"]

    def _create_task(self, client: TestClient, pid: str) -> str:
        resp = client.post(
            f"{API_PREFIX}/tasks",
            json={"projectId": pid, "goal": "错误测试", "startUrl": "https://example.com"},
        )
        return resp.json()["taskId"]


# ── Security headers ──────────────────────────────────────────────────────────


class TestSecurityHeaders:
    """SecurityHeadersMiddleware 注入的安全响应头验证。"""

    def test_security_headers_present(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "no-referrer"
        assert resp.headers.get("cross-origin-opener-policy") == "same-origin"

    def test_security_headers_on_error(self, client: TestClient) -> None:
        """4xx 响应也应包含安全头。"""
        resp = client.get(f"{API_PREFIX}/projects/no-such")
        assert resp.status_code == 404
        assert resp.headers.get("x-content-type-options") == "nosniff"


# ── CORS ──────────────────────────────────────────────────────────────────────


class TestCORS:
    """CORS 中间件契约。"""

    def test_allowed_origin_returns_header(self, client: TestClient) -> None:
        resp = client.get(
            f"{API_PREFIX}/tasks",
            headers={"Origin": "http://localhost:8000"},
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8000"

    def test_disallowed_origin_no_header(self, client: TestClient) -> None:
        resp = client.get(
            f"{API_PREFIX}/tasks",
            headers={"Origin": "https://evil.com"},
        )
        assert "access-control-allow-origin" not in resp.headers
