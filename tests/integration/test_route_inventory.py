"""阶段四：路由清单测试。

从 OpenAPI schema 验证关联/白盒路由数量并与实际测试覆盖交叉验证。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from argus_py.infra.events import EventBus
from argus_py.infra.worker import TaskWorker
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers.factories import make_app_stack

API_PREFIX = "/argus/api"
pytestmark = [pytest.mark.integration]


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


@pytest.fixture(scope="module")
def openapi_paths(tmp_path_factory) -> dict[str, Any]:
    """返回 OpenAPI paths dict（模块级夹具，一次启动）。
    tmp_path_factory 是 scope="module" 可用的 fixture，自动按 scope 清理。"""
    tmp_path = tmp_path_factory.mktemp("route_inv")

    stack = make_app_stack(tmp_path)
    model_cfg_service = ModelConfigService(ModelConfigSQLiteStorage(tmp_path / "models.db"))
    worker = TaskWorker(
        queue=stack.queue, lifecycle=stack.lifecycle, reader=stack.reader, handlers={}
    )
    event_bus = EventBus(history_limit=50)

    app = FastAPI(title="Route Inventory Test")
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

    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    return schema.get("paths", {})


class TestCorrelationRouteInventory:
    """关联路由清单。"""

    def test_correlation_route_count(self, openapi_paths) -> None:
        corr_paths = [p for p in openapi_paths if "correlation" in p.lower()]
        # 当前预期 11 个路径模式
        assert len(corr_paths) >= 8, (
            f"Expected at least 8 correlation paths, got {len(corr_paths)}: {sorted(corr_paths)}"
        )

    def test_correlation_get_routes_exist(self, openapi_paths) -> None:
        corr_get = {
            p
            for p, methods in openapi_paths.items()
            if "correlation" in p.lower() and "get" in methods
        }
        required_endpoints = {
            "attempts",
            "summary",
            "endpoint-evidence",
            "unmatched-requests",
            "finding-evidence",
            "capture-quality",
            "uncovered-endpoints",
        }
        found = {k for path in corr_get for k in required_endpoints if k in path}
        missing = required_endpoints - found
        assert not missing, f"Missing GET endpoints: {missing}. Found paths: {sorted(corr_get)}"

    def test_correlation_post_routes_exist(self, openapi_paths) -> None:
        corr_post = {
            p
            for p, methods in openapi_paths.items()
            if "correlation" in p.lower() and "post" in methods
        }
        required_ops = {"bind-analysis", "retry", "recalculate"}
        found = {k for path in corr_post for k in required_ops if k in path}
        missing = required_ops - found
        assert not missing, f"Missing POST endpoints: {missing}. Found: {sorted(corr_post)}"

    def test_correlation_runs_by_task_route(self, openapi_paths) -> None:
        """GET /correlation-runs?taskId= 路由存在。"""
        base_path = f"{API_PREFIX}/correlation-runs"
        assert base_path in openapi_paths, (
            f"No correlation-runs list endpoint, paths: {sorted(openapi_paths.keys())}"
        )
        methods = openapi_paths[base_path]
        assert "get" in methods, f"correlation-runs endpoint has no GET method: {methods}"


class TestWhiteboxRouteInventory:
    """白盒/分析路由清单。"""

    def test_whitebox_analysis_routes_exist(self, openapi_paths) -> None:
        analysis_paths = {
            p for p in openapi_paths if "analysis" in p.lower() or "whitebox" in p.lower()
        }
        assert len(analysis_paths) > 0, (
            f"No analysis routes found. All paths: {sorted(openapi_paths.keys())[:20]}"
        )
