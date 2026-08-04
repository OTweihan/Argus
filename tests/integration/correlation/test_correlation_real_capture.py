"""阶段四：真实采集管线 E2E 测试 — P2#1。

不走 DB 直写 HttpRequestEvidence，而是通过 BrowserSession 的事件处理
链模拟 Playwright 的 request/response/finished 事件，验证完整管线：

  Playwright 事件 → _on_request → 同源过滤 + 脱敏 + 资源类型过滤
  → _on_response → 状态码记录 → _on_request_finished → completed → flush
  → Writer 持久化 → DB insert → 读回校验

这是阶段四中唯一触发 BrowserSession 内部过滤/脱敏逻辑的集成测试。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from argus_py.browser.base import BrowserSession
from argus_py.correlation.enums import (
    CorrelationEligibility,
    RequestOutcome,
    RequestOwner,
)
from argus_py.correlation.models import HttpRequestEvidence, _CapturedRequest
from argus_py.task.storage import TaskSQLiteStorage

from tests.integration.correlation._fixtures import setup_base_tables

pytestmark = [pytest.mark.integration]


# ── Mock Request / Response（模拟 Playwright 对象）─────────────────


class _MockFrame:
    def __init__(self, page: MagicMock) -> None:
        self.page = page


class _MockRequest:
    __slots__ = ("url", "resource_type", "method", "service_worker", "frame", "failure")

    def __init__(
        self,
        url: str,
        resource_type: str = "fetch",
        method: str = "GET",
        service_worker: bool = False,
        frame: _MockFrame | None = None,
        failure: str | None = None,
    ) -> None:
        self.url = url
        self.resource_type = resource_type
        self.method = method
        self.service_worker = service_worker
        self.frame = frame
        self.failure = failure


class _MockResponse:
    __slots__ = ("request", "status", "from_service_worker")

    def __init__(
        self, request: _MockRequest, status: int = 200, from_service_worker: bool = False
    ) -> None:
        self.request = request
        self.status = status
        self.from_service_worker = from_service_worker


def _make_page_mock() -> MagicMock:
    page = MagicMock()
    page.url = "https://example.com/page"
    return page


def _make_request(url: str, **kw: Any) -> _MockRequest:
    frame_kw: dict[str, Any] = {}
    if "frame" in kw:
        frame_kw["frame"] = kw.pop("frame")
    elif "page" in kw:
        page = kw.pop("page")
        frame_kw["frame"] = _MockFrame(page)
    return _MockRequest(url, **kw, **frame_kw)


def _make_response(request: _MockRequest, status: int = 200) -> _MockResponse:
    return _MockResponse(request, status=status)


# ── 管线测试 ───────────────────────────────────────────────────────


class TestRequestCapturePipeline:
    """通过 BrowserSession._on_request → _on_response → _on_finished
    的完整链路，验证真实过滤/脱敏/持久化行为。"""

    @staticmethod
    def _configure_writer(sess: BrowserSession, storage: TaskSQLiteStorage) -> None:
        """使用与组合根相同的领域模型转换配置请求证据 writer。"""

        async def persist(batch: list[_CapturedRequest]) -> None:
            items = [
                HttpRequestEvidence(
                    request_evidence_id=f"req-capture-{cap.sequence}",
                    blackbox_run_id="bb1",
                    task_id="t1",
                    step_execution_id=cap.step_execution_id,
                    step_attempt=cap.step_attempt,
                    request_sequence=cap.sequence,
                    http_method=cap.method,
                    normalized_path=cap.normalized_path,
                    display_path=cap.display_path,
                    origin=cap.origin,
                    resource_type=cap.resource_type,
                    endpoint_match_eligibility=CorrelationEligibility.CONFIRMED_ELIGIBLE,
                    response_status=cap.response_status,
                    outcome=cap.outcome,
                    failure_code=cap.failure_code,
                    request_owner=RequestOwner(cap.request_owner),
                    response_from_service_worker=cap.response_from_service_worker,
                    page_sequence=cap.page_sequence,
                    captured_at=cap.started_at,
                    finished_at=cap.finished_at,
                )
                for cap in batch
            ]
            storage.insert_http_request_batch(items)

        sess._persist_fn = persist
        sess._writer_task = asyncio.create_task(sess._request_writer())

    @pytest.mark.asyncio
    async def test_same_origin_request_captured_and_persisted(self, tmp_path: Path) -> None:
        """同源 fetch 请求 → 进入 pending → finished → completed → flush → DB。"""
        storage = setup_base_tables(tmp_path / "capture.db")

        sess = BrowserSession(MagicMock())
        sess.set_allowed_origins(["https://example.com"])
        sess._flush_batch_threshold = 2  # 小阈值以便触发 flush
        self._configure_writer(sess, storage)

        page = _make_page_mock()

        try:
            # 模拟 3 个同源请求
            req1 = _make_request("https://example.com/api/users", page=page)
            req2 = _make_request("https://example.com/api/orders", page=page)
            req3 = _make_request("https://example.com/api/products", page=page)

            sess._on_request(req1)  # type: ignore[arg-type]
            sess._on_request(req2)  # type: ignore[arg-type]
            sess._on_request(req3)  # type: ignore[arg-type]

            # 验证 pending 中有 3 条
            assert len(sess._pending_requests) == 3
            assert sess._accepted_started == 3
            assert sess._filtered_cross_origin == 0
            assert sess._filtered_by_resource_type == 0

            # 模拟响应
            sess._on_response(_make_response(req1, 200))  # type: ignore[arg-type]
            sess._on_response(_make_response(req2, 201))  # type: ignore[arg-type]
            sess._on_response(_make_response(req3, 404))  # type: ignore[arg-type]

            # 模拟完成 → 触发 flush
            sess._on_request_finished(req1)  # type: ignore[arg-type]
            sess._on_request_finished(req2)  # type: ignore[arg-type]
            sess._on_request_finished(req3)  # type: ignore[arg-type]

            # flush 后应无 completed 残留
            assert len(sess._completed_requests) == 1  # 阈值=2，flush 了 2，剩 1
            await asyncio.sleep(0.1)  # 等待 writer 处理

            # 排空
            await sess.finish_request_capture()

            # 验证 DB 中有 3 条
            stored, total = storage.list_http_requests("bb1", limit=100)
            assert total == 3
            paths = {r.normalized_path for r in stored}
            assert "/api/users" in paths
            assert "/api/orders" in paths
            assert "/api/products" in paths

            # 验证 display_path 无敏感信息
            for r in stored:
                assert r.display_path == r.normalized_path

            # 验证采集质量
            quality = sess.get_capture_quality()
            assert quality["total_observed"] == 3
            assert quality["filtered_cross_origin"] == 0
            assert quality["filtered_by_resource_type"] == 0
        finally:
            if sess._writer_task and not sess._writer_task.done():
                sess._writer_task.cancel()

    @pytest.mark.asyncio
    async def test_cross_origin_filtered(self, tmp_path: Path) -> None:
        """跨域请求 → 被过滤 → 不进入 pending。"""
        setup_base_tables(tmp_path / "cross_origin.db")

        sess = BrowserSession(MagicMock())
        sess.set_allowed_origins(["https://example.com"])
        sess._flush_batch_threshold = 2

        page = _make_page_mock()

        try:
            # 保留请求对象引用，贴近 Playwright 在请求完成前的对象生命周期。
            requests = [
                _make_request("https://example.com/api/users", page=page),
                _make_request("https://evil.com/steal", page=page),
                _make_request("https://example.com/api/orders", page=page),
            ]
            for request in requests:
                sess._on_request(request)  # type: ignore[arg-type]

            assert len(sess._pending_requests) == 2  # 只捕获同源
            assert sess._accepted_started == 2
            assert sess._filtered_cross_origin == 1
            assert sess._total_observed == 3

            quality = sess.get_capture_quality()
            assert quality["filtered_cross_origin"] == 1
        finally:
            pass

    @pytest.mark.asyncio
    async def test_resource_type_filtered(self, tmp_path: Path) -> None:
        """image/stylesheet/script → 被过滤。"""
        setup_base_tables(tmp_path / "resource_filter.db")

        sess = BrowserSession(MagicMock())
        sess.set_allowed_origins(["https://example.com"])
        page = _make_page_mock()

        requests = [
            _make_request("https://example.com/api/data", resource_type="fetch", page=page),
            _make_request("https://example.com/logo.png", resource_type="image", page=page),
            _make_request("https://example.com/style.css", resource_type="stylesheet", page=page),
            _make_request("https://example.com/app.js", resource_type="script", page=page),
            _make_request("https://example.com/ws", resource_type="websocket", page=page),
        ]
        for request in requests:
            sess._on_request(request)  # type: ignore[arg-type]

        assert len(sess._pending_requests) == 1  # 只有 fetch
        assert sess._filtered_by_resource_type == 3
        assert sess._filtered_websocket_count == 1

        quality = sess.get_capture_quality()
        assert quality["filtered_by_resource_type"] == 3
        assert quality["filtered_websocket_count"] == 1

    @pytest.mark.asyncio
    async def test_sensitive_path_sanitized_in_display(self, tmp_path: Path) -> None:
        """含 UUID/Token/JWT 的路径 → display_path 脱敏 → 通过整个管线持久化后
        DB 中的 display_path 不含敏感信息。
        """
        storage = setup_base_tables(tmp_path / "sanitize.db")

        sess = BrowserSession(MagicMock())
        sess.set_allowed_origins(["https://example.com"])
        sess._flush_batch_threshold = 2
        self._configure_writer(sess, storage)

        page = _make_page_mock()

        try:
            # UUID 在路径中
            url_uuid = "https://example.com/api/users/550e8400-e29b-41d4-a716-446655440000/profile"
            # hex token 在路径中
            url_token = "https://example.com/download/abcdef0123456789abcdef0123456789abcdef"
            # JWT 在路径中
            jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
            url_jwt = f"https://example.com/api/auth/{jwt}"
            # 普通路径（控制组）
            url_normal = "https://example.com/api/v1/products/42"

            for url in [url_uuid, url_token, url_jwt, url_normal]:
                req = _make_request(url, page=page)
                sess._on_request(req)  # type: ignore[arg-type]
                sess._on_response(_make_response(req, 200))  # type: ignore[arg-type]
                sess._on_request_finished(req)  # type: ignore[arg-type]

            # 排空
            await asyncio.sleep(0.1)
            await sess.finish_request_capture()

            # 读 DB 验证
            stored, total = storage.list_http_requests("bb1", limit=100)
            assert total == 4

            for r in stored:
                display = r.display_path
                normalized = r.normalized_path
                # 敏感数据不应出现在任何持久化路径字段中
                assert "550e8400" not in display
                assert "abcdef0123456789" not in display
                assert jwt not in display
                assert "550e8400" not in normalized
                assert "abcdef0123456789" not in normalized
                assert jwt not in normalized
                assert display == normalized
                # 普通路径保持不变
                if "/api/v1/products/42" in normalized:
                    assert display == normalized
        finally:
            if sess._writer_task and not sess._writer_task.done():
                sess._writer_task.cancel()

    @pytest.mark.asyncio
    async def test_request_failed_marked_network_failed(self, tmp_path: Path) -> None:
        """请求失败 → outcome 为 NETWORK_FAILED → 持久化。"""
        storage = setup_base_tables(tmp_path / "failed.db")

        sess = BrowserSession(MagicMock())
        sess.set_allowed_origins(["https://example.com"])
        sess._flush_batch_threshold = 2
        self._configure_writer(sess, storage)

        page = _make_page_mock()

        try:
            req = _make_request(
                "https://example.com/api/failing",
                page=page,
                failure="net::ERR_CONNECTION_RESET",
            )
            sess._on_request(req)  # type: ignore[arg-type]

            # 模拟失败（没有 _on_response 先触发）
            req_failure = req
            sess._on_request_failed(req_failure)  # type: ignore[arg-type]

            await asyncio.sleep(0.1)
            await sess.finish_request_capture()

            stored, total = storage.list_http_requests("bb1", limit=100)
            assert total == 1
            assert stored[0].outcome == RequestOutcome.NETWORK_FAILED
        finally:
            if sess._writer_task and not sess._writer_task.done():
                sess._writer_task.cancel()

    @pytest.mark.asyncio
    async def test_pending_requests_abandoned_on_finish(self, tmp_path: Path) -> None:
        """finish_request_capture 将残留 pending 标记为 ABANDONED。"""
        storage = setup_base_tables(tmp_path / "abandoned.db")

        sess = BrowserSession(MagicMock())
        sess.set_allowed_origins(["https://example.com"])
        sess._flush_batch_threshold = 50  # 高阈值，不自动 flush
        self._configure_writer(sess, storage)

        page = _make_page_mock()

        try:
            # 发起请求但不触发 finished
            req1 = _make_request("https://example.com/api/pending1", page=page)
            req2 = _make_request("https://example.com/api/pending2", page=page)
            sess._on_request(req1)  # type: ignore[arg-type]
            sess._on_request(req2)  # type: ignore[arg-type]
            sess._on_response(_make_response(req1, 200))  # type: ignore[arg-type]
            sess._on_response(_make_response(req2, 200))  # type: ignore[arg-type]

            assert len(sess._pending_requests) == 2

            # 结束采集
            await sess.finish_request_capture()

            stored, total = storage.list_http_requests("bb1", limit=100)
            assert total == 2
            for r in stored:
                assert r.outcome == RequestOutcome.ABANDONED
        finally:
            if sess._writer_task and not sess._writer_task.done():
                sess._writer_task.cancel()

    @pytest.mark.asyncio
    async def test_writer_queue_empty_no_hang(self) -> None:
        """空队列 + finish → writer 正常退出，不挂死。"""
        sess = BrowserSession(MagicMock())

        async def noop(batch: list[_CapturedRequest]) -> None:
            pass

        sess._persist_fn = noop
        sess._writer_task = asyncio.create_task(sess._request_writer())
        # 无 pending，无 completed
        sess._completed_requests = []
        sess._pending_requests = {}

        try:
            await asyncio.wait_for(sess.finish_request_capture(), timeout=3)
        finally:
            if sess._writer_task and not sess._writer_task.done():
                sess._writer_task.cancel()

    @pytest.mark.asyncio
    async def test_full_pipeline_end_to_end(self, tmp_path: Path) -> None:
        """完整管线：多种请求混合 → 过滤 + 脱敏 → 持久化 → 读回验证完整性。"""
        storage = setup_base_tables(tmp_path / "full.db")

        sess = BrowserSession(MagicMock())
        sess.set_allowed_origins(["https://example.com"])
        sess._flush_batch_threshold = 3
        self._configure_writer(sess, storage)

        page = _make_page_mock()

        try:
            # 混合请求：
            # 1. 同源 + fetch → 捕获
            # 2. 跨域 → 过滤
            # 3. 同源 + image → 过滤（资源类型）
            # 4. 同源 + document（含 JWT token）→ 捕获并脱敏
            # 5. 同源 + fetch → 捕获

            jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"

            req1 = _make_request("https://example.com/api/users", resource_type="fetch", page=page)
            req2 = _make_request("https://evil.com/steal", resource_type="fetch", page=page)
            req3 = _make_request("https://example.com/logo.png", resource_type="image", page=page)
            req4 = _make_request(
                f"https://example.com/api/auth/{jwt}", resource_type="document", page=page
            )
            req5 = _make_request("https://example.com/api/orders", resource_type="fetch", page=page)

            for req in [req1, req2, req3, req4, req5]:
                sess._on_request(req)  # type: ignore[arg-type]

            # 只有 req1, req4, req5 进入 pending
            assert len(sess._pending_requests) == 3
            assert sess._total_observed == 5
            assert sess._filtered_cross_origin == 1
            assert sess._filtered_by_resource_type == 1

            # 响应 + 完成
            for req in [req1, req4, req5]:
                sess._on_response(_make_response(req, 200))  # type: ignore[arg-type]
                sess._on_request_finished(req)  # type: ignore[arg-type]

            await asyncio.sleep(0.1)
            await sess.finish_request_capture()

            # DB 验证
            stored, total = storage.list_http_requests("bb1", limit=100)
            assert total == 3

            # 分别验证每条
            by_path = {r.normalized_path: r for r in stored}

            assert "/api/users" in by_path
            assert by_path["/api/users"].display_path == "/api/users"
            assert by_path["/api/users"].outcome == RequestOutcome.COMPLETED

            assert "/api/orders" in by_path
            assert by_path["/api/orders"].outcome == RequestOutcome.COMPLETED

            # JWT 请求：持久化前已脱敏，两个路径字段均不含原文。
            jwt_path = "/api/auth/{token}"
            assert jwt_path in by_path
            assert by_path[jwt_path].display_path == jwt_path

            # 采集质量
            quality = sess.get_capture_quality()
            assert quality["total_observed"] == 5
            assert quality["accepted_started"] == 3
            assert quality["filtered_cross_origin"] == 1
            assert quality["filtered_by_resource_type"] == 1
            # persisted = accepted - failed
            assert (
                quality["persisted_count"]
                == quality["accepted_started"] - quality["persistence_failed"]
            )
        finally:
            if sess._writer_task and not sess._writer_task.done():
                sess._writer_task.cancel()
