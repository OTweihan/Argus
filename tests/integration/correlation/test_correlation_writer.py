"""阶段四：Writer 故障测试。

覆盖：队列满、writer 重试/失败、STOP sentinel、finish_request_capture 行为。
通过 mock 测试 BrowserSession 的 writer 循环，不需要真实浏览器。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from argus_py.browser.base import _STOP
from argus_py.correlation.enums import RequestOutcome


@pytest.fixture
async def session():
    """创建 BrowserSession（mock PlaywrightClient，只测试 writer 队列）。"""
    from argus_py.browser.base import BrowserSession

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    sess = BrowserSession(mock_client)
    return sess


def _make_captured_request():
    """创建最小化 _CapturedRequest 用于 writer 测试。
    注意：_CapturedRequest.__slots__ 不包含 outcome 等动态属性，
    这些在 _on_response 回调中设置。
    """
    from argus_py.correlation.models import _CapturedRequest

    return _CapturedRequest(
        sequence=1,
        step_execution_id="step-1",
        step_attempt=1,
        page_sequence=1,
        method="GET",
        origin="https://example.com",
        normalized_path="/api/test",
        display_path="/api/test",
        resource_type="fetch",
        request_owner="FRAME",
        started_at="2024-01-01T00:00:00",
    )


class TestWriterQueueFull:
    @pytest.mark.asyncio
    async def test_queue_full_drops_and_truncates(self, session) -> None:
        """队列满时 put_nowait 触发 QueueFull → drop + truncated。"""
        session._persist_queue = asyncio.Queue(maxsize=1)
        session._persist_queue.put_nowait([{}])
        # 设置足够低 threshold + 足够多 completed 以触发 flush
        session._flush_batch_threshold = 3
        session._completed_requests = [{} for _ in range(5)]

        session._flush_to_queue_if_needed()

        assert len(session._completed_requests) == 5  # 留在缓冲区
        assert session._dropped_writer_queue_limit > 0
        assert session._truncated is True


class TestWriterRetry:
    @pytest.mark.asyncio
    async def test_writer_retry_succeeds_on_second_try(self, session) -> None:
        call_count = 0

        async def _flaky(batch):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first attempt")

        session._persist_fn = _flaky
        session._persist_queue.put_nowait([{"r": "test"}])
        session._persist_queue.put_nowait(_STOP)

        await asyncio.wait_for(session._request_writer(), timeout=5)
        assert call_count == 2
        assert session._writer_failed_batch_count == 0
        assert session._writer_retry_count == 1

    @pytest.mark.asyncio
    async def test_writer_three_failures_marks_failed(self, session) -> None:
        async def _always_fail(batch):
            raise RuntimeError("failed")

        session._persist_fn = _always_fail
        batch = [{"r": "1"}, {"r": "2"}]
        session._persist_queue.put_nowait(batch)
        session._persist_queue.put_nowait(_STOP)

        await asyncio.wait_for(session._request_writer(), timeout=5)

        assert session._writer_failed_batch_count == 1
        assert session._persistence_failed == 2

    @pytest.mark.asyncio
    async def test_writer_stop_sentinel_exits(self, session) -> None:
        session._persist_queue.put_nowait(_STOP)
        await asyncio.wait_for(session._request_writer(), timeout=5)


class TestFinishRequestCapture:
    @pytest.mark.asyncio
    async def test_pending_requests_marked_abandoned(self, session) -> None:
        """pending 请求在 finish 时标记为 ABANDONED。"""
        cap = _make_captured_request()
        cap.outcome = RequestOutcome.COMPLETED  # 将被覆盖
        session._pending_requests = {id(cap): cap}
        session._completed_requests = []

        async def _noop(batch):
            pass

        session._persist_fn = _noop
        session._writer_task = asyncio.create_task(session._request_writer())

        try:
            await asyncio.wait_for(session.finish_request_capture(), timeout=5)
        finally:
            if session._writer_task and not session._writer_task.done():
                session._writer_task.cancel()

        assert cap.outcome == RequestOutcome.ABANDONED

    @pytest.mark.asyncio
    async def test_writer_exits_gracefully_via_stop(self, session) -> None:
        """正常 STOP 路径：writer 能正常退出，finish 不挂死。"""

        async def _noop(batch):
            pass

        session._persist_fn = _noop
        session._writer_task = asyncio.create_task(session._request_writer())

        # 正常完成：无 pending，无 completed
        session._completed_requests = []
        session._pending_requests = {}

        try:
            await asyncio.wait_for(session.finish_request_capture(), timeout=5)
        finally:
            if session._writer_task and not session._writer_task.done():
                session._writer_task.cancel()


class TestCaptureQuality:
    @pytest.mark.asyncio
    async def test_quality_after_writer_failures(self, session) -> None:
        session._persistence_failed = 5
        session._accepted_started = 100
        session._writer_failed_batch_count = 2
        session._writer_retry_count = 3
        session._dropped_writer_queue_limit = 10
        session._truncated = True

        q = session.get_capture_quality()
        assert q["persisted_count"] == 95
        assert q["persistence_failed"] == 5
        assert q["writer_failed_batch_count"] == 2
        assert q["writer_retry_count"] == 3
        assert q["dropped_writer_queue_limit"] == 10
        assert q["truncated"] == 1
