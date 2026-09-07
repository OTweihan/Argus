"""诊断日志导出与诊断包单元/路由测试。"""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import threading
import time
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
    BundleCapacityError,
    BundleRecord,
    DiagnosticsBundleRegistry,
    build_diagnostics_bundle,
    build_log_export,
)
from argus_py.observability.diagnostics_service import DiagnosticsService
from argus_py.observability.diagnostics_store import (
    DiagnosticsScanBudget,
    FileDiagnosticsLogStore,
)
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


class TestScanBudgetD01:
    def test_shared_budget_accumulates_across_pages(self, store: FileDiagnosticsLogStore) -> None:
        """导出级预算跨分页累计，不会每页重置。"""
        from argus_py.observability.diagnostics_store import DiagnosticsPage, DiagnosticsQuery

        remainders: list[int] = []
        calls = {"n": 0}

        def fake_search(query: DiagnosticsQuery, *, scan_budget=None):  # noqa: ANN001
            calls["n"] += 1
            assert scan_budget is not None
            remainders.append(scan_budget.remaining)
            # 每次 search 消耗 100 字节，模拟跨页累计
            scan_budget.consume(100)
            # 第一页给 1 条并 has_more，迫使第二页
            if calls["n"] == 1:
                from argus_py.observability.diagnostics_store import DiagnosticsEvent

                event = DiagnosticsEvent(
                    event_id="e1",
                    timestamp=_BASE.isoformat(),
                    level="INFO",
                    component="python",
                    module="t",
                    message="page1",
                    request_id=None,
                    run_id=None,
                    exception=None,
                )
                return DiagnosticsPage(
                    items=[event], next_cursor="c1", has_more=True, scan_limited=False
                )
            return DiagnosticsPage(items=[], next_cursor=None, has_more=False, scan_limited=False)

        store.search = fake_search  # type: ignore[method-assign]
        budget = DiagnosticsScanBudget(max_bytes=250)
        result = build_log_export(store, max_events=50, scan_budget=budget)
        try:
            assert calls["n"] >= 2
            assert remainders[0] == 250
            assert remainders[1] == 150  # 第一页已 consume 100
            assert budget.consumed == 200
        finally:
            Path(result.path).unlink(missing_ok=True)

    def test_cancel_event_stops_collection(self, store: FileDiagnosticsLogStore) -> None:
        cancel = threading.Event()
        cancel.set()
        budget = DiagnosticsScanBudget(max_bytes=64 * 1024 * 1024, cancel_event=cancel)
        result = build_log_export(store, max_events=50, scan_budget=budget)
        try:
            assert result.event_count == 0
            assert result.scan_limited is True
            assert budget.limited is True
        finally:
            Path(result.path).unlink(missing_ok=True)

    def test_guarded_holds_slot_until_worker_finishes(self) -> None:
        """超时后 semaphore 仍占用至后台线程结束（D-01）。"""
        from concurrent.futures import ThreadPoolExecutor

        import argus_py.api.routes.diagnostics as routes
        from argus_py.observability.context import set_io_executor

        async def _run() -> None:
            gate = asyncio.Semaphore(1)
            started = threading.Event()
            release_worker = threading.Event()
            pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="diag-test")
            set_io_executor(pool)
            try:

                def slow() -> str:
                    started.set()
                    assert release_worker.wait(timeout=5.0)
                    return "done"

                settings = ServerSettings(diagnostics_query_timeout_seconds=0.05)

                async def invoke() -> None:
                    with pytest.raises(Exception) as exc_info:
                        await routes._guarded(gate, settings, "test.slow", slow)
                    assert getattr(exc_info.value, "status_code", None) == 503

                task = asyncio.create_task(invoke())
                # 不可在事件循环线程上 blocking wait，否则 worker 无法调度。
                deadline = time.monotonic() + 5.0
                while not started.is_set() and time.monotonic() < deadline:
                    await asyncio.sleep(0.01)
                assert started.is_set(), "后台 worker 未启动"
                # 后台仍在跑时闸门应占满
                assert gate.locked()
                # 此时第二个 acquire 不应立即成功（槽位未释放）
                blocked = asyncio.create_task(gate.acquire())
                await asyncio.sleep(0.05)
                assert not blocked.done()
                release_worker.set()
                await task
                await asyncio.wait_for(blocked, timeout=1.0)
                gate.release()
            finally:
                set_io_executor(None)
                pool.shutdown(wait=True, cancel_futures=False)

        asyncio.run(_run())


class TestBundleRegistryD03:
    def test_capacity_rejects_extra_items(self, store: FileDiagnosticsLogStore) -> None:
        settings = ServerSettings()
        service = DiagnosticsService(settings, store)
        reg = DiagnosticsBundleRegistry(ttl_seconds=300, max_items=1, max_total_bytes=10**9)
        first = build_diagnostics_bundle(service, store, reg, max_events=5)
        try:
            with pytest.raises(BundleCapacityError):
                build_diagnostics_bundle(service, store, reg, max_events=5)
            assert reg.stats()["items"] == 1
        finally:
            claimed = reg.claim(first.bundle_id)
            if claimed:
                Path(claimed.path).unlink(missing_ok=True)

    def test_capacity_rejects_total_bytes(self, tmp_path: Path) -> None:
        """总字节上限：直接 put 超大 record。"""
        # 本用例不依赖 pytest tmp_path 沙箱写权限之外的路径时跳过 zip 构建
        reg = DiagnosticsBundleRegistry(ttl_seconds=300, max_items=10, max_total_bytes=100)
        path = _WORK_ROOT / f"cap-{uuid.uuid4().hex[:8]}.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 40)
        rec1 = BundleRecord(
            bundle_id="diag_a",
            path=str(path),
            created_at=time.time(),
            expires_at=time.time() + 300,
            event_count=1,
            truncated=False,
            scan_limited=False,
            size_bytes=40,
        )
        reg.put(rec1)
        path2 = _WORK_ROOT / f"cap2-{uuid.uuid4().hex[:8]}.zip"
        path2.write_bytes(b"y" * 80)
        rec2 = BundleRecord(
            bundle_id="diag_b",
            path=str(path2),
            created_at=time.time(),
            expires_at=time.time() + 300,
            event_count=1,
            truncated=False,
            scan_limited=False,
            size_bytes=80,
        )
        try:
            with pytest.raises(BundleCapacityError):
                reg.put(rec2)
        finally:
            reg.clear_all()
            path.unlink(missing_ok=True)
            path2.unlink(missing_ok=True)

    def test_purge_expired_removes_file(self) -> None:
        reg = DiagnosticsBundleRegistry(ttl_seconds=300, max_items=10, max_total_bytes=10**9)
        path = _WORK_ROOT / f"exp-{uuid.uuid4().hex[:8]}.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"zip")
        now = time.time()
        reg.put(
            BundleRecord(
                bundle_id="diag_old",
                path=str(path),
                created_at=now - 10,
                expires_at=now - 1,
                event_count=0,
                truncated=False,
                scan_limited=False,
                size_bytes=3,
            )
        )
        removed = reg.purge_expired()
        assert removed >= 1
        assert reg.stats()["items"] == 0
        assert not path.exists()

    def test_route_capacity_returns_429(self, logs_root: Path) -> None:
        store = FileDiagnosticsLogStore(logs_root)
        settings = ServerSettings(
            diagnostics_export_timeout_seconds=30.0,
            diagnostics_max_concurrent_queries=2,
        )
        reg = DiagnosticsBundleRegistry(ttl_seconds=300, max_items=1, max_total_bytes=10**9)
        app = FastAPI()
        app.include_router(diagnostics.router, prefix=API_PREFIX)
        app.dependency_overrides.update(
            {
                get_diagnostics_store: lambda: store,
                get_diagnostics_service: lambda: DiagnosticsService(settings, store),
                get_diagnostics_semaphore: lambda: asyncio.Semaphore(2),
                get_diagnostics_bundle_registry: lambda: reg,
                get_server_settings: lambda: settings,
            }
        )
        with TestClient(app) as client:
            first = client.post(f"{API_PREFIX}/diagnostics/bundles", json={"maxEvents": 5})
            assert first.status_code == 201
            second = client.post(f"{API_PREFIX}/diagnostics/bundles", json={"maxEvents": 5})
            assert second.status_code == 429
            claimed = reg.claim(first.json()["bundleId"])
            if claimed:
                Path(claimed.path).unlink(missing_ok=True)

    def test_put_capacity_still_unlinks_expired(self) -> None:
        """容量拒绝时，同一次 put 摘掉的过期文件仍必须删除（review 高优）。"""
        reg = DiagnosticsBundleRegistry(ttl_seconds=300, max_items=1, max_total_bytes=10**9)
        expired_path = _WORK_ROOT / f"expired-{uuid.uuid4().hex[:8]}.zip"
        expired_path.parent.mkdir(parents=True, exist_ok=True)
        expired_path.write_bytes(b"old")
        now = time.time()
        reg.put(
            BundleRecord(
                bundle_id="diag_expired",
                path=str(expired_path),
                created_at=now - 10,
                expires_at=now - 1,
                event_count=0,
                truncated=False,
                scan_limited=False,
                size_bytes=3,
            )
        )
        # 再塞一个未过期的占满 max_items=1
        live_path = _WORK_ROOT / f"live-{uuid.uuid4().hex[:8]}.zip"
        live_path.write_bytes(b"live")
        reg.put(
            BundleRecord(
                bundle_id="diag_live",
                path=str(live_path),
                created_at=now,
                expires_at=now + 300,
                event_count=0,
                truncated=False,
                scan_limited=False,
                size_bytes=4,
            )
        )
        # 手动把 expired 再塞回去模拟「put 时顺带 purge」：
        # 当前 items=1(live)；再 put 一个 expired 记录后立刻再 put 新包触发容量满+purge
        # 更直接：reg 内已有 live；构造另一个 expired 进 _items 后 put 新包
        another_expired = _WORK_ROOT / f"exp2-{uuid.uuid4().hex[:8]}.zip"
        another_expired.write_bytes(b"e2")
        with reg._lock:  # noqa: SLF001
            reg._items["diag_exp2"] = BundleRecord(
                bundle_id="diag_exp2",
                path=str(another_expired),
                created_at=now - 5,
                expires_at=now - 1,
                event_count=0,
                truncated=False,
                scan_limited=False,
                size_bytes=2,
            )
        newbie = _WORK_ROOT / f"new-{uuid.uuid4().hex[:8]}.zip"
        newbie.write_bytes(b"new")
        try:
            with pytest.raises(BundleCapacityError):
                reg.put(
                    BundleRecord(
                        bundle_id="diag_new",
                        path=str(newbie),
                        created_at=now,
                        expires_at=now + 300,
                        event_count=0,
                        truncated=False,
                        scan_limited=False,
                        size_bytes=3,
                    )
                )
            # 过期文件必须被删；live 仍在；newbie 由调用方负责（此处保留）
            assert not another_expired.exists()
            assert reg.stats()["items"] == 1
            assert reg.get("diag_live") is not None
        finally:
            reg.clear_all()
            for p in (expired_path, live_path, another_expired, newbie):
                p.unlink(missing_ok=True)

    def test_cleanup_uses_injected_registry_not_global(self) -> None:
        """超时 cleanup 必须 pop 与 put 相同的 registry 实例。"""
        reg = DiagnosticsBundleRegistry(ttl_seconds=300, max_items=10, max_total_bytes=10**9)
        path = _WORK_ROOT / f"cleanup-{uuid.uuid4().hex[:8]}.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"zip-data")
        now = time.time()
        rec = BundleRecord(
            bundle_id="diag_cleanup",
            path=str(path),
            created_at=now,
            expires_at=now + 300,
            event_count=1,
            truncated=False,
            scan_limited=False,
            size_bytes=8,
        )
        reg.put(rec)
        diagnostics._cleanup_guarded_result(rec, registry=reg)
        assert reg.stats()["items"] == 0
        assert not path.exists()

    def test_claim_without_purge_leaves_other_expired(self) -> None:
        """下载 claim(purge_expired=False) 不顺带删其他过期包。"""
        reg = DiagnosticsBundleRegistry(ttl_seconds=300, max_items=10, max_total_bytes=10**9)
        now = time.time()
        exp_path = _WORK_ROOT / f"c-exp-{uuid.uuid4().hex[:8]}.zip"
        live_path = _WORK_ROOT / f"c-live-{uuid.uuid4().hex[:8]}.zip"
        exp_path.parent.mkdir(parents=True, exist_ok=True)
        exp_path.write_bytes(b"e")
        live_path.write_bytes(b"l")
        reg.put(
            BundleRecord(
                bundle_id="diag_l",
                path=str(live_path),
                created_at=now,
                expires_at=now + 300,
                event_count=0,
                truncated=False,
                scan_limited=False,
                size_bytes=1,
            )
        )
        # put() 会先 purge，不能靠 put 塞过期项；直接注入模拟「到期但尚未定时回收」。
        with reg._lock:  # noqa: SLF001
            reg._items["diag_e"] = BundleRecord(
                bundle_id="diag_e",
                path=str(exp_path),
                created_at=now - 10,
                expires_at=now - 1,
                event_count=0,
                truncated=False,
                scan_limited=False,
                size_bytes=1,
            )
        claimed = reg.claim("diag_l", purge_expired=False)
        assert claimed is not None
        # 过期项仍在登记中（交给定时 purge）
        assert reg.stats()["items"] == 1
        assert exp_path.exists()
        removed = reg.purge_expired()
        assert removed >= 1
        assert not exp_path.exists()
        live_path.unlink(missing_ok=True)
