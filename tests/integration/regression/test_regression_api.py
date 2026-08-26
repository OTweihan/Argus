"""回归闭环 REST API 契约测试（ASGI TestClient，无 worker/lifespan）。

覆盖：用例 CRUD、批次创建/查询、错误码稳定性、项目隔离与分页字段。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from argus_py.api.dependencies import get_regression_service
from argus_py.api.middleware import configure_middleware
from argus_py.api.routes import regression as regression_routes
from argus_py.config.server_settings import ServerSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.helpers.factories import AppStack, make_app_stack

API_PREFIX = "/argus/api"
pytestmark = [pytest.mark.integration]


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, AppStack]]:
    stack = make_app_stack(tmp_path)
    app = FastAPI(title="Argus Regression API Test")
    app.router.lifespan_context = _noop_lifespan
    configure_middleware(app, ServerSettings())
    app.include_router(regression_routes.router, prefix=API_PREFIX)
    app.dependency_overrides[get_regression_service] = lambda: stack.regression

    with TestClient(app) as test_client:
        yield test_client, stack


def _project(stack: AppStack) -> str:
    return stack.project_service.create_project(
        name="契约项目", base_url="http://localhost:9000"
    ).project_id


_CASE_PAYLOAD: dict[str, Any] = {
    "name": "登录回归",
    "taskType": "blackbox",
    "goal": "验证登录功能",
    "startUrl": "http://localhost:9000/login",
    "maxSteps": 5,
    "timeoutSeconds": 60,
    "captureScreenshots": False,
    "parameters": {},
    "enabled": True,
    "displayOrder": 1,
}


class TestCaseEndpoints:
    def test_create_and_get_case_camelcase(self, client: tuple[TestClient, AppStack]) -> None:
        http, stack = client
        pid = _project(stack)
        resp = http.post(f"{API_PREFIX}/projects/{pid}/regression-cases", json=_CASE_PAYLOAD)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["caseId"].startswith("regcase-")
        assert body["taskType"] == "blackbox"
        assert body["displayOrder"] == 1
        assert body["captureScreenshots"] is False

        got = http.get(f"{API_PREFIX}/regression-cases/{body['caseId']}")
        assert got.status_code == 200
        assert got.json()["goal"] == "验证登录功能"

    def test_list_cases(self, client: tuple[TestClient, AppStack]) -> None:
        http, stack = client
        pid = _project(stack)
        http.post(f"{API_PREFIX}/projects/{pid}/regression-cases", json=_CASE_PAYLOAD)
        other = stack.project_service.create_project(name="其他项目")
        http.post(
            f"{API_PREFIX}/projects/{other.project_id}/regression-cases",
            json={**_CASE_PAYLOAD, "name": "别家的"},
        )

        listed = http.get(f"{API_PREFIX}/projects/{pid}/regression-cases").json()
        assert listed["total"] == 1
        assert listed["cases"][0]["projectId"] == pid

    def test_invalid_payload_maps_domain_error(self, client: tuple[TestClient, AppStack]) -> None:
        http, stack = client
        pid = _project(stack)
        resp = http.post(
            f"{API_PREFIX}/projects/{pid}/regression-cases",
            json={**_CASE_PAYLOAD, "goal": ""},
        )
        assert resp.status_code in (400, 422)

    def test_unknown_project_404(self, client: tuple[TestClient, AppStack]) -> None:
        http, _ = client
        resp = http.post(f"{API_PREFIX}/projects/proj-none/regression-cases", json=_CASE_PAYLOAD)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_update_and_delete(self, client: tuple[TestClient, AppStack]) -> None:
        http, stack = client
        pid = _project(stack)
        case_id = http.post(
            f"{API_PREFIX}/projects/{pid}/regression-cases", json=_CASE_PAYLOAD
        ).json()["caseId"]

        updated = http.put(f"{API_PREFIX}/regression-cases/{case_id}", json={"enabled": False})
        assert updated.status_code == 200
        assert updated.json()["enabled"] is False

        deleted = http.delete(f"{API_PREFIX}/regression-cases/{case_id}")
        assert deleted.status_code == 204
        assert http.get(f"{API_PREFIX}/regression-cases/{case_id}").status_code == 404


class TestRunEndpoints:
    def _prepare(self, http: TestClient, stack: AppStack) -> str:
        pid = _project(stack)
        created = http.post(f"{API_PREFIX}/projects/{pid}/regression-cases", json=_CASE_PAYLOAD)
        assert created.status_code == 201, created.text
        return pid

    def test_create_run_returns_accepted_shape(self, client: tuple[TestClient, AppStack]) -> None:
        http, stack = client
        pid = self._prepare(http, stack)
        resp = http.post(f"{API_PREFIX}/projects/{pid}/regression-runs", json={})
        assert resp.status_code == 202, resp.text
        run = resp.json()
        assert run["runId"].startswith("regrun-")
        assert run["status"] == "running"
        assert run["triggerSource"] == "api"
        assert run["isBaseline"] is False

        detail = http.get(f"{API_PREFIX}/regression-runs/{run['runId']}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["run"]["runId"] == run["runId"]
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["taskId"]
        assert item["taskStatus"] == "pending"
        assert isinstance(body["summary"], dict)

    def test_run_not_found_stable_code(self, client: tuple[TestClient, AppStack]) -> None:
        http, _ = client
        resp = http.get(f"{API_PREFIX}/regression-runs/regrun-none")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "REGRESSION_RUN_NOT_FOUND"

    def test_list_runs_pagination_fields(self, client: tuple[TestClient, AppStack]) -> None:
        http, stack = client
        pid = self._prepare(http, stack)
        http.post(f"{API_PREFIX}/projects/{pid}/regression-runs", json={})
        page = http.get(
            f"{API_PREFIX}/projects/{pid}/regression-runs", params={"offset": 0, "limit": 10}
        )
        assert page.status_code == 200
        body = page.json()
        assert body["total"] == 1
        assert body["offset"] == 0
        assert body["limit"] == 10
        assert len(body["runs"]) == 1

    def test_baseline_rejects_running_batch(self, client: tuple[TestClient, AppStack]) -> None:
        http, stack = client
        pid = self._prepare(http, stack)
        run_id = http.post(f"{API_PREFIX}/projects/{pid}/regression-runs", json={}).json()["runId"]

        resp = http.put(f"{API_PREFIX}/projects/{pid}/regression-baseline", json={"runId": run_id})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "BASELINE_ONLY_COMPLETED_BATCH"

        empty = http.get(f"{API_PREFIX}/projects/{pid}/regression-baseline")
        assert empty.status_code == 200
        assert empty.json()["baselineRunId"] is None
