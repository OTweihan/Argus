"""阶段四：白盒客户端补充测试。

覆盖：409 幂等冲突、409 result not ready、ConnectTimeout/ReadTimeout 分类、
非 JSON 响应体。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from argus_py.whitebox.client import (
    WhiteboxClient,
    WhiteboxClientError,
    WhiteboxIdempotencyConflictError,
    WhiteboxResultNotReadyError,
    WhiteboxTransientError,
)


def _mock_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
        resp.text = str(json_data)
    else:
        resp.json.side_effect = ValueError("not json")
        resp.text = "<html>Internal Server Error</html>"
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture(scope="module")
def client() -> WhiteboxClient:
    return WhiteboxClient(base_url="http://test-host:8081", request_timeout=10)


# ── 409 冲突 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_job_409_conflict(client: WhiteboxClient) -> None:
    """409 幂等冲突 → WhiteboxIdempotencyConflictError。"""
    with patch.object(client, "_get_client") as mock_get:
        mock_http = AsyncMock()
        resp = _mock_response(409, {"error": "参数冲突", "clientRequestId": "t1:1"})
        resp.is_success = False
        mock_http.request.return_value = resp
        mock_get.return_value = mock_http

        with pytest.raises(WhiteboxIdempotencyConflictError):
            await client.submit_analyze_job("/tmp/project")


@pytest.mark.asyncio
async def test_get_result_409_not_ready(client: WhiteboxClient) -> None:
    """409 result not ready → WhiteboxResultNotReadyError。"""
    with patch.object(client, "_get_client") as mock_get:
        mock_http = AsyncMock()
        resp = _mock_response(409, {"error": "Result not ready"})
        resp.is_success = False
        mock_http.request.return_value = resp
        mock_get.return_value = mock_http

        with pytest.raises(WhiteboxResultNotReadyError):
            await client.get_analyze_job_result("job-1")


# ── 超时分类 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_timeout_is_transient(client: WhiteboxClient) -> None:
    """ConnectTimeout → WhiteboxTransientError。"""
    with patch.object(client, "_get_client") as mock_get:
        mock_http = AsyncMock()
        mock_http.request.side_effect = httpx.ConnectTimeout("connection timed out")
        mock_get.return_value = mock_http

        with pytest.raises(WhiteboxTransientError):
            await client.get_analyze_job("job-1")


@pytest.mark.asyncio
async def test_read_timeout_is_transient(client: WhiteboxClient) -> None:
    """ReadTimeout → WhiteboxTransientError。"""
    with patch.object(client, "_get_client") as mock_get:
        mock_http = AsyncMock()
        mock_http.request.side_effect = httpx.ReadTimeout("read timed out")
        mock_get.return_value = mock_http

        with pytest.raises(WhiteboxTransientError):
            await client.get_analyze_job("job-1")


# ── 非 JSON 响应体 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_json_text_response_raises(client: WhiteboxClient) -> None:
    """HTML 响应 → WhiteboxClientError。"""
    with patch.object(client, "_get_client") as mock_get:
        mock_http = AsyncMock()
        mock_http.request.return_value = _mock_response(200, None)
        mock_get.return_value = mock_http

        with pytest.raises(WhiteboxClientError, match="有效 JSON"):
            await client.analyze("/tmp/project")


@pytest.mark.asyncio
async def test_non_json_empty_body_raises(client: WhiteboxClient) -> None:
    """空响应体 → WhiteboxClientError。"""
    with patch.object(client, "_get_client") as mock_get:
        mock_http = AsyncMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ""
        resp.json.side_effect = ValueError("empty")
        resp.raise_for_status.return_value = None
        mock_http.request.return_value = resp
        mock_get.return_value = mock_http

        with pytest.raises(WhiteboxClientError, match="有效 JSON"):
            await client.analyze("/tmp/project")
