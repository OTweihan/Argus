"""诊断中心路由集成测试（资源隔离与错误映射，方案第 17 章）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from argus_py.api.dependencies import (
    get_diagnostics_semaphore,
    get_diagnostics_service,
    get_diagnostics_store,
    get_server_settings,
)
from argus_py.api.routes import diagnostics
from argus_py.config.server_settings import ServerSettings
from argus_py.observability.diagnostics_service import DiagnosticsService
from argus_py.observability.diagnostics_store import FileDiagnosticsLogStore
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_PREFIX = "/argus/api"
RUN_ID = "20260826-120000"
_BASE = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)


def _runtime_line(
    ts: datetime,
    message: str,
    *,
    level: str = "INFO",
    request_id: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "timestamp": ts.isoformat(),
        "level": level,
        "logger": "argus_py.demo",
        "message": message,
        "module": "demo",
    }
    if request_id:
        payload["requestId"] = request_id
    return json.dumps(payload, ensure_ascii=False)


def _dev_line(ts: datetime, service: str, channel: str, content: str) -> str:
    return f"{ts.isoformat().replace('+00:00', 'Z')} [{service}][{channel}] {content}"


@pytest.fixture
def logs_root(tmp_path: Path) -> Path:
    runtime_dir = tmp_path / "runtime" / "python"
    runtime_dir.mkdir(parents=True)
    lines = [
        _runtime_line(_BASE - timedelta(minutes=30), "oldest info"),
        _runtime_line(
            _BASE - timedelta(minutes=10), "boom happened", level="ERROR", request_id="req_abc"
        ),
        _runtime_line(_BASE, "newest info", request_id="req_abc"),
    ]
    (runtime_dir / "argus.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    run_dir = tmp_path / "dev" / RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "python.log").write_text(
        _dev_line(_BASE - timedelta(minutes=5), "python", "stdout", "python booting") + "\n",
        encoding="utf-8",
    )
    (run_dir / "java.log").write_text(
        _dev_line(_BASE - timedelta(minutes=3), "java", "stdout", "java started") + "\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def client(logs_root: Path) -> Iterator[TestClient]:
    store = FileDiagnosticsLogStore(logs_root)
    settings = ServerSettings()

    app = FastAPI()
    app.include_router(diagnostics.router, prefix=API_PREFIX)
    app.dependency_overrides.update(
        {
            get_diagnostics_store: lambda: store,
            get_diagnostics_service: lambda: DiagnosticsService(settings, store),
            get_diagnostics_semaphore: lambda: asyncio.Semaphore(2),
            get_server_settings: lambda: settings,
        }
    )
    with TestClient(app) as test_client:
        yield test_client


class TestLogsEndpoint:
    def test_search_returns_camel_case_page(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/logs", params={"limit": 10})
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"items", "nextCursor", "hasMore", "scanLimited"}
        entry = body["items"][0]
        assert {
            "eventId",
            "timestamp",
            "level",
            "component",
            "module",
            "message",
            "requestId",
            "runId",
            "exception",
        } <= set(entry)

    def test_level_filter_applied(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/logs", params={"level": "ERROR"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["message"] == "boom happened"

    def test_request_id_alias(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/logs", params={"requestId": "req_abc"})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2

    def test_limit_over_cap_rejected(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/logs", params={"limit": 500})
        assert resp.status_code == 422

    def test_unknown_component_bad_request(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/logs", params={"component": "nope"})
        assert resp.status_code == 400

    def test_invalid_cursor_bad_request(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/logs", params={"cursor": "@@@bad@@@"})
        assert resp.status_code == 400

    def test_detail_then_context(self, client: TestClient) -> None:
        page = client.get(f"{API_PREFIX}/diagnostics/logs", params={"level": "ERROR"}).json()
        event_id = page["items"][0]["eventId"]

        detail = client.get(f"{API_PREFIX}/diagnostics/logs/{event_id}")
        assert detail.status_code == 200
        detail_body = detail.json()
        assert detail_body["raw"]["level"] == "ERROR"
        assert {"filePath", "lineNumber"} <= set(detail_body["source"])

        context = client.get(
            f"{API_PREFIX}/diagnostics/logs/{event_id}/context",
            params={"before": 1, "after": 1},
        )
        assert context.status_code == 200
        assert any(e["message"] == "boom happened" for e in context.json()["items"])

    def test_detail_unknown_event_404(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/logs/garbage-id")
        assert resp.status_code == 404


class TestTraceEndpoint:
    def test_trace_by_request_id_ordered(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/requests/req_abc")
        assert resp.status_code == 200
        body = resp.json()
        assert body["requestId"] == "req_abc"
        messages = [e["message"] for e in body["items"]]
        assert messages == ["boom happened", "newest info"]

    def test_trace_empty_ok(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/requests/req_none")
        assert resp.status_code == 200
        assert resp.json()["items"] == []


class TestRunsEndpoints:
    def test_list_runs(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/runs")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert [r["runId"] for r in runs] == [RUN_ID]
        assert runs[0]["totalBytes"] > 0

    def test_get_run_detail(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/runs/{RUN_ID}")
        assert resp.status_code == 200
        assert {f["name"] for f in resp.json()["files"]} >= {"python.log", "java.log"}

    def test_run_not_found_404(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/runs/19990101-000000")
        assert resp.status_code == 404

    def test_run_logs_keyword(self, client: TestClient) -> None:
        resp = client.get(
            f"{API_PREFIX}/diagnostics/runs/{RUN_ID}/logs", params={"keyword": "started"}
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert [e["message"] for e in items] == ["java started"]

    def test_run_logs_invalid_id_400(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/runs/not-a-run/logs")
        assert resp.status_code == 400


class TestServicesEndpoint:
    def test_services_shape(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/services")
        assert resp.status_code == 200
        body = resp.json()
        names = {s["name"] for s in body["services"]}
        assert {"python", "java", "database", "web"} <= names
        assert body["logsUsage"]["totalBytes"] > 0
        assert "checkedAt" in body


class TestJavaProbe:
    async def test_probe_bypasses_system_proxy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Java 健康探测必须 trust_env=False（Windows 系统代理会拦截 localhost → 502）。"""
        import httpx
        from argus_py.observability.diagnostics_service import DiagnosticsService

        captured: dict[str, object] = {}

        class _FakeResponse:
            status_code = 200

            def json(self) -> dict[str, str]:
                return {"status": "UP"}

        class _FakeAsyncClient:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            async def __aenter__(self) -> "_FakeAsyncClient":
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

            async def get(self, url: str) -> _FakeResponse:
                return _FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
        settings = ServerSettings(java_analyzer_url="http://localhost:8081")
        service = DiagnosticsService(settings, store=None)  # type: ignore[arg-type]

        status = await service.java_status()

        assert captured.get("trust_env") is False
        assert status.status == "ok"

    async def test_probe_cache_hit_within_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TTL 窗口内重复探测直接返回缓存，不重复发起 HTTP。"""
        import httpx
        from argus_py.observability.diagnostics_service import DiagnosticsService

        calls = {"count": 0}

        class _FakeResponse:
            status_code = 200

            def json(self) -> dict[str, str]:
                return {"status": "UP"}

        class _FakeAsyncClient:
            def __init__(self, **kwargs: object) -> None:
                pass

            async def __aenter__(self) -> "_FakeAsyncClient":
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

            async def get(self, url: str) -> _FakeResponse:
                calls["count"] += 1
                return _FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
        settings = ServerSettings(java_analyzer_url="http://localhost:8081")
        service = DiagnosticsService(settings, store=None)  # type: ignore[arg-type]

        first = await service.java_status()
        second = await service.java_status()

        assert calls["count"] == 1
        assert first.status == second.status == "ok"


class TestConcurrencyGuard:
    def test_saturated_gate_returns_429(self, logs_root: Path) -> None:
        store = FileDiagnosticsLogStore(logs_root)

        class _LockedGate:
            """模拟并发闸门饱和：locked() 恒真，请求必须快速 429。"""

            def locked(self) -> bool:
                return True

            async def __aenter__(self) -> "_LockedGate":
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

        app = FastAPI()
        app.include_router(diagnostics.router, prefix=API_PREFIX)
        app.dependency_overrides.update(
            {
                get_diagnostics_store: lambda: store,
                get_server_settings: lambda: ServerSettings(),
                get_diagnostics_semaphore: lambda: _LockedGate(),
            }
        )
        with TestClient(app) as test_client:
            resp = test_client.get(f"{API_PREFIX}/diagnostics/logs")
            assert resp.status_code == 429


class TestPhase2Endpoints:
    def test_overview_shape(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert "runId" in body
        assert "services" in body
        assert "errorCountLastHour" in body
        assert "checkedAt" in body
        names = {s["name"] for s in body["services"]}
        assert "python" in names
        assert "java" in names

    def test_system_info_shape(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/system")
        assert resp.status_code == 200
        body = resp.json()
        assert body["argusVersion"]
        assert body["runId"]
        assert body["logsDirectory"]
        assert "javaRuntimeLogsPresent" in body
        assert body["javaStatus"]["name"] == "java"

    def test_frontend_event_accepted(self, client: TestClient, logs_root: Path) -> None:
        resp = client.post(
            f"{API_PREFIX}/diagnostics/frontend-events",
            json={
                "message": "boom from ui",
                "level": "ERROR",
                "errorType": "TypeError",
                "module": "test",
            },
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["accepted"] is True
        assert body["eventId"]
        path = logs_root / "runtime" / "web" / "frontend-events.jsonl"
        assert path.is_file()
        line = path.read_text(encoding="utf-8").strip().splitlines()[-1]
        payload = json.loads(line)
        assert payload["component"] == "web"
        assert payload["message"] == "boom from ui"

    def test_system_events_list(self, client: TestClient, logs_root: Path) -> None:
        from argus_py.observability.context import init_process_run_id, reset_process_run_id
        from argus_py.observability.system_events import append_system_event

        reset_process_run_id()
        init_process_run_id("run_test_events")
        try:
            append_system_event(
                "service.started",
                result="success",
                details={"pid": 1},
                logs_root=logs_root,
            )
        finally:
            reset_process_run_id()

        resp = client.get(f"{API_PREFIX}/diagnostics/events")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(e["message"] == "service.started" for e in items)
        assert all(e["component"] == "system" for e in items)
