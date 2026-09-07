"""诊断日志导出与诊断包单元/路由测试。"""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import uuid
import zipfile
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from argus_py.api.dependencies import (
    get_diagnostics_bundle_registry,
    get_diagnostics_semaphore,
    get_diagnostics_service,
    get_diagnostics_store,
    get_server_settings,
)
from argus_py.api.routes import diagnostics
from argus_py.config.server_settings import ServerSettings
from argus_py.observability.diagnostics_export import (
    DiagnosticsBundleRegistry,
    build_diagnostics_bundle,
    build_log_export,
)
from argus_py.observability.diagnostics_service import DiagnosticsService
from argus_py.observability.diagnostics_store import FileDiagnosticsLogStore
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_PREFIX = "/argus/api"
_BASE = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
# 避免依赖 pytest tmp_path（当前沙箱对 basetemp 有权限限制）
_WORK_ROOT = Path(__file__).resolve().parents[2] / ".tmp-diag-export-tests"


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


@pytest.fixture
def logs_root() -> Iterator[Path]:
    """每测独立 uuid 子目录，避免并行/残留踩踏。"""
    root = _WORK_ROOT / f"logs-{uuid.uuid4().hex[:8]}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    runtime_dir = root / "runtime" / "python"
    runtime_dir.mkdir(parents=True)
    lines = [
        _runtime_line(_BASE - timedelta(minutes=30), "oldest info"),
        _runtime_line(
            _BASE - timedelta(minutes=10),
            "boom api_key=super-secret-token",
            level="ERROR",
            request_id="req_export",
        ),
        _runtime_line(
            _BASE - timedelta(minutes=5),
            "critical failure",
            level="CRITICAL",
            request_id="req_export",
        ),
        _runtime_line(_BASE, "newest info", request_id="req_export"),
    ]
    (runtime_dir / "argus.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def store(logs_root: Path) -> FileDiagnosticsLogStore:
    return FileDiagnosticsLogStore(logs_root)


@pytest.fixture
def registry() -> DiagnosticsBundleRegistry:
    return DiagnosticsBundleRegistry(ttl_seconds=300)


@pytest.fixture
def client(logs_root: Path, registry: DiagnosticsBundleRegistry) -> Iterator[TestClient]:
    store = FileDiagnosticsLogStore(logs_root)
    settings = ServerSettings(
        diagnostics_query_timeout_seconds=5.0,
        diagnostics_export_timeout_seconds=30.0,
        diagnostics_max_concurrent_queries=2,
    )

    app = FastAPI()
    app.include_router(diagnostics.router, prefix=API_PREFIX)
    app.dependency_overrides.update(
        {
            get_diagnostics_store: lambda: store,
            get_diagnostics_service: lambda: DiagnosticsService(settings, store),
            get_diagnostics_semaphore: lambda: asyncio.Semaphore(2),
            get_diagnostics_bundle_registry: lambda: registry,
            get_server_settings: lambda: settings,
        }
    )
    with TestClient(app) as test_client:
        yield test_client


class TestBuildLogExport:
    def test_export_redacts_sensitive_and_writes_manifest(
        self, store: FileDiagnosticsLogStore
    ) -> None:
        result = build_log_export(store, levels=["ERROR"], max_events=50)
        assert result.event_count >= 1
        assert Path(result.path).is_file()
        try:
            with zipfile.ZipFile(result.path) as zf:
                assert {"manifest.json", "logs.ndjson"} <= set(zf.namelist())
                manifest = json.loads(zf.read("manifest.json"))
                assert manifest["kind"] == "diagnostics-log-export"
                assert manifest["eventCount"] == result.event_count
                assert manifest["filters"]["levelSemantics"] == "min-level"
                body = zf.read("logs.ndjson").decode("utf-8")
                assert "super-secret-token" not in body
                assert "REDACTED" in body
                # min-level ERROR 应包含 CRITICAL
                assert "critical failure" in body
        finally:
            Path(result.path).unlink(missing_ok=True)

    def test_export_max_events_truncates(self, store: FileDiagnosticsLogStore) -> None:
        result = build_log_export(store, max_events=1)
        assert result.event_count == 1
        assert result.truncated is True
        Path(result.path).unlink(missing_ok=True)

    def test_export_request_id_filter(self, store: FileDiagnosticsLogStore) -> None:
        result = build_log_export(store, request_id="req_export", max_events=50)
        # ERROR + CRITICAL + newest info
        assert result.event_count == 3
        Path(result.path).unlink(missing_ok=True)

    def test_export_keyword_filter(self, store: FileDiagnosticsLogStore) -> None:
        result = build_log_export(store, keyword="critical", max_events=50)
        assert result.event_count == 1
        Path(result.path).unlink(missing_ok=True)

    def test_build_failure_unlinks_temp(
        self, store: FileDiagnosticsLogStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import argus_py.observability.diagnostics_export as mod

        created: list[str] = []
        real_open = mod._open_temp_zip

        def tracking_open() -> tuple[object, str]:
            tmp, path = real_open()
            created.append(path)
            return tmp, path

        def boom(*_a: object, **_k: object) -> object:
            raise RuntimeError("zip write failed")

        monkeypatch.setattr(mod, "_open_temp_zip", tracking_open)
        monkeypatch.setattr(mod.zipfile, "ZipFile", boom)
        with pytest.raises(RuntimeError, match="zip write failed"):
            build_log_export(store, max_events=10)
        assert created
        for path in created:
            assert not Path(path).exists()


class TestBuildBundle:
    def test_bundle_contains_overview_and_registers(
        self,
        store: FileDiagnosticsLogStore,
        registry: DiagnosticsBundleRegistry,
    ) -> None:
        settings = ServerSettings()
        service = DiagnosticsService(settings, store)
        record = build_diagnostics_bundle(service, store, registry, max_events=50, levels=["ERROR"])
        assert registry.get(record.bundle_id) is not None
        assert Path(record.path).is_file()
        try:
            with zipfile.ZipFile(record.path) as zf:
                names = set(zf.namelist())
                assert "overview.json" in names
                assert "system.json" in names
                assert "logs.ndjson" in names
                assert "manifest.json" in names
                manifest = json.loads(zf.read("manifest.json"))
                for name in manifest["contents"]:
                    assert name in names
                overview = json.loads(zf.read("overview.json"))
                assert "runId" in overview
                assert "services" in overview
        finally:
            registry.pop(record.bundle_id)
            Path(record.path).unlink(missing_ok=True)

    def test_registry_expires(self, store: FileDiagnosticsLogStore) -> None:
        settings = ServerSettings()
        service = DiagnosticsService(settings, store)
        short = DiagnosticsBundleRegistry(ttl_seconds=0)
        record = build_diagnostics_bundle(service, store, short, max_events=10)
        assert short.get(record.bundle_id) is None
        assert short.claim(record.bundle_id) is None
        Path(record.path).unlink(missing_ok=True)

    def test_claim_is_one_shot(self, store: FileDiagnosticsLogStore) -> None:
        settings = ServerSettings()
        service = DiagnosticsService(settings, store)
        reg = DiagnosticsBundleRegistry(ttl_seconds=300)
        record = build_diagnostics_bundle(service, store, reg, max_events=10)
        first = reg.claim(record.bundle_id)
        assert first is not None
        assert reg.claim(record.bundle_id) is None
        Path(record.path).unlink(missing_ok=True)


class TestExportRoutes:
    def test_post_export_returns_zip(self, client: TestClient) -> None:
        resp = client.post(
            f"{API_PREFIX}/diagnostics/export",
            json={"levels": ["ERROR"], "maxEvents": 100},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/zip")
        # ERROR min-level → ERROR + CRITICAL
        assert resp.headers.get("x-argus-export-event-count") == "2"
        assert zipfile.is_zipfile(io.BytesIO(resp.content))

    def test_post_export_invalid_component_400(self, client: TestClient) -> None:
        resp = client.post(
            f"{API_PREFIX}/diagnostics/export",
            json={"components": ["nope"]},
        )
        assert resp.status_code == 400

    def test_create_and_download_bundle(self, client: TestClient) -> None:
        create = client.post(
            f"{API_PREFIX}/diagnostics/bundles",
            json={"maxEvents": 50, "levels": ["ERROR"]},
        )
        assert create.status_code == 201
        body = create.json()
        assert {
            "bundleId",
            "downloadPath",
            "expiresAt",
            "eventCount",
            "truncated",
            "scanLimited",
            "sizeBytes",
        } <= set(body)
        assert body["downloadPath"] == f"diagnostics/bundles/{body['bundleId']}"
        bundle_id = body["bundleId"]

        download = client.get(f"{API_PREFIX}/diagnostics/bundles/{bundle_id}")
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("application/zip")
        assert zipfile.is_zipfile(io.BytesIO(download.content))

        again = client.get(f"{API_PREFIX}/diagnostics/bundles/{bundle_id}")
        assert again.status_code == 404

    def test_download_unknown_bundle_404(self, client: TestClient) -> None:
        resp = client.get(f"{API_PREFIX}/diagnostics/bundles/diag_missing")
        assert resp.status_code == 404
