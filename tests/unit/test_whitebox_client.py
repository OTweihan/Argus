"""白盒客户端单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from argus_py.whitebox.client import WhiteboxClient, WhiteboxClientError
from argus_py.whitebox.models import WhiteboxResult


def _mock_response(status_code: int, json_data: dict) -> MagicMock:
    """创建模拟的 httpx.Response 对象。"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    resp.text = str(json_data)
    return resp


def _mock_bad_json_response() -> MagicMock:
    resp = _mock_response(200, {})
    resp.text = "not-json"
    resp.json.side_effect = ValueError("bad json")
    return resp


@pytest.fixture(scope="module")
def client() -> WhiteboxClient:
    return WhiteboxClient(base_url="http://test-host:8081", request_timeout=10)


@pytest.mark.asyncio
async def test_analyze_success(client: WhiteboxClient) -> None:
    """验证分析成功后的数据反序列化。"""
    mock_response_data = {
        "endpoints": [
            {
                "path": "/api/hello",
                "httpMethod": "GET",
                "controllerClass": "com.example.HelloController",
                "controllerMethod": "hello",
                "parameters": [],
                "returnType": "String",
            }
        ],
        "callGraph": {
            "com.example.HelloController#hello": {
                "className": "com.example.HelloController",
                "methodName": "hello",
                "methodSignature": "String hello()",
                "callees": ["com.example.GreetingService#greet"],
            }
        },
        "findings": [
            {
                "ruleId": "EMPTY_CATCH",
                "severity": "MEDIUM",
                "title": "空 catch 块",
                "description": "catch 块为空",
                "filePath": "src/main/java/com/example/BadCode.java",
                "lineNumber": 12,
                "snippet": "catch (Exception e) {}",
            }
        ],
    }

    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = _mock_response(200, mock_response_data)
        mock_get_client.return_value = mock_http

        result = await client.analyze("/tmp/test-project", scope="all")

    assert isinstance(result, WhiteboxResult)
    assert len(result.endpoints) == 1
    assert result.endpoints[0].path == "/api/hello"
    assert result.endpoints[0].http_method == "GET"
    assert len(result.call_graph.nodes) == 1
    assert "com.example.HelloController#hello" in result.call_graph.nodes
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "EMPTY_CATCH"
    # 跨服务链路：默认注入 X-Request-ID
    kwargs = mock_http.request.await_args.kwargs
    headers = kwargs.get("headers") or {}
    assert "X-Request-ID" in headers
    assert headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_analyze_empty_response(client: WhiteboxClient) -> None:
    """验证空结果的正确处理。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = _mock_response(
            200, {"endpoints": [], "callGraph": {}, "findings": []}
        )
        mock_get_client.return_value = mock_http

        result = await client.analyze("/tmp/empty-project")

    assert len(result.endpoints) == 0
    assert len(result.call_graph.nodes) == 0
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_analyze_diagnostics_classpath_details(client: WhiteboxClient) -> None:
    """验证 classpath 诊断字段可反序列化。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = _mock_response(
            200,
            {
                "endpoints": [],
                "callGraph": {},
                "findings": [],
                "diagnostics": {
                    "classpathAvailable": False,
                    "classpathSource": "none",
                    "classpathCommand": "mvn dependency:build-classpath",
                    "classpathExitCode": 1,
                    "classpathDurationMs": 1234,
                    "classpathStdoutTail": "[INFO] Building demo",
                    "classpathStderrTail": "[ERROR] failed",
                    "classpathTimedOut": False,
                    "classpathErrors": ["Maven exited with code 1"],
                },
            },
        )
        mock_get_client.return_value = mock_http

        result = await client.analyze("/tmp/test-project")

    assert result.diagnostics is not None
    assert result.diagnostics.classpath_command == "mvn dependency:build-classpath"
    assert result.diagnostics.classpath_exit_code == 1
    assert result.diagnostics.classpath_duration_ms == 1234
    assert result.diagnostics.classpath_stderr_tail == "[ERROR] failed"


@pytest.mark.asyncio
async def test_request_id_header_uses_context_and_preserves_explicit(
    client: WhiteboxClient,
) -> None:
    """注入 context request_id；调用方显式头不被覆盖。"""
    from argus_py.observability.context import bind_context

    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = _mock_response(
            200, {"endpoints": [], "callGraph": {}, "findings": []}
        )
        mock_get_client.return_value = mock_http

        with bind_context(request_id="req_from_context"):
            await client.analyze("/tmp/test-project")
        headers = mock_http.request.await_args.kwargs.get("headers") or {}
        assert headers.get("X-Request-ID") == "req_from_context"

        mock_http.request.reset_mock()
        mock_http.request.return_value = _mock_response(
            200, {"endpoints": [], "callGraph": {}, "findings": []}
        )
        await client._request(
            "GET",
            "/argus/api/analyze/jobs/x",
            headers={"X-Request-ID": "req_explicit"},
        )
        headers = mock_http.request.await_args.kwargs.get("headers") or {}
        assert headers.get("X-Request-ID") == "req_explicit"


@pytest.mark.asyncio
async def test_analyze_wraps_invalid_json(client: WhiteboxClient) -> None:
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = _mock_bad_json_response()
        mock_get_client.return_value = mock_http

        with pytest.raises(WhiteboxClientError, match="有效 JSON"):
            await client.analyze("/tmp/test-project")


@pytest.mark.asyncio
async def test_submit_analyze_job_wraps_invalid_json(client: WhiteboxClient) -> None:
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = _mock_bad_json_response()
        mock_get_client.return_value = mock_http

        with pytest.raises(WhiteboxClientError, match="有效 JSON"):
            await client.submit_analyze_job("/tmp/test-project")


@pytest.mark.asyncio
async def test_submit_analyze_job_sends_source_revision(client: WhiteboxClient) -> None:
    """O-07：提交作业时携带 sourceRevision/snapshotDigest，且不污染旧字段。"""
    response = _mock_response(
        200,
        {
            "jobId": "job-1",
            "status": "PENDING",
            "stage": "queued",
            "createdAt": "2026-05-25T00:00:00Z",
            "events": [],
        },
    )
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = response
        mock_get_client.return_value = mock_http

        await client.submit_analyze_job(
            "/tmp/test-project",
            scope="all",
            source_revision="abc123",
            snapshot_digest="deadbeef",
        )

    call_args = mock_http.request.call_args
    method, path = call_args.args
    payload = call_args.kwargs["json"]
    assert method == "POST"
    assert path == "/argus/api/analyze/jobs"
    assert payload["sourcePath"] == "/tmp/test-project"
    assert payload["sourceRevision"] == "abc123"
    assert payload["snapshotDigest"] == "deadbeef"
    # 未提供时默认不携带（旧客户端兼容）
    assert "clientRequestId" not in payload
    assert "timeoutSeconds" not in payload


@pytest.mark.asyncio
async def test_get_analyze_job_result_wraps_invalid_json(client: WhiteboxClient) -> None:
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = _mock_bad_json_response()
        mock_get_client.return_value = mock_http

        with pytest.raises(WhiteboxClientError, match="有效 JSON"):
            await client.get_analyze_job_result("job-1")


@pytest.mark.asyncio
async def test_analyze_wraps_non_object_response(client: WhiteboxClient) -> None:
    response = _mock_response(200, {})
    response.json.return_value = []
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = response
        mock_get_client.return_value = mock_http

        with pytest.raises(WhiteboxClientError, match="响应结构不是对象"):
            await client.analyze("/tmp/test-project")


@pytest.mark.asyncio
async def test_analyze_http_error(client: WhiteboxClient) -> None:
    """验证 HTTP 错误时抛出类型化异常。"""
    from argus_py.whitebox.client import WhiteboxPermanentError

    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        err_resp = _mock_response(400, {"error": "bad request"})
        err_resp.is_success = False
        mock_http.request.return_value = err_resp
        mock_get_client.return_value = mock_http

        with pytest.raises(WhiteboxPermanentError):
            await client.analyze("/tmp/test-project")


@pytest.mark.asyncio
async def test_analyze_connect_error_fails(client: WhiteboxClient) -> None:
    """验证连接错误时抛出 WhiteboxClientError（同步 analyze 包装瞬态错误）。"""

    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.side_effect = httpx.ConnectError("Connection refused")
        mock_get_client.return_value = mock_http

        with pytest.raises(WhiteboxClientError):
            await client.analyze("/tmp/test-project")

    assert mock_http.request.call_count == 1  # analyze does not retry


@pytest.mark.asyncio
async def test_health_ok(client: WhiteboxClient) -> None:
    """验证健康检查返回 True。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.get.return_value = _mock_response(200, {"status": "UP"})
        mock_get_client.return_value = mock_http

        assert await client.health() is True


@pytest.mark.asyncio
async def test_health_fail(client: WhiteboxClient) -> None:
    """验证健康检查返回 False。"""
    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch("argus_py.whitebox.client.logger.debug") as mock_debug,
    ):
        mock_http = AsyncMock()
        mock_http.get.side_effect = ConnectionError("refused")
        mock_get_client.return_value = mock_http

        assert await client.health() is False

    mock_debug.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_scope_callgraph(client: WhiteboxClient) -> None:
    """验证 scope 参数正确传递。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = _mock_response(
            200, {"endpoints": [], "callGraph": {}, "findings": []}
        )
        mock_get_client.return_value = mock_http

        await client.analyze(
            "/tmp/test", scope="callgraph", target_modules=["han-modules/han-admin"]
        )

        call_kwargs = mock_http.request.call_args.kwargs
        assert call_kwargs["json"]["scope"] == "callgraph"
        assert call_kwargs["json"]["targetModules"] == ["han-modules/han-admin"]


@pytest.mark.asyncio
async def test_submit_and_query_analyze_job(client: WhiteboxClient) -> None:
    """验证异步作业接口请求和状态解析。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()

        def _request_side_effect(method, path, **kwargs):
            if method == "POST":
                return _mock_response(
                    200,
                    {
                        "jobId": "job-1",
                        "status": "RUNNING",
                        "stage": "classpath",
                        "createdAt": "2026-05-25T00:00:00Z",
                        "events": [
                            {
                                "timestamp": "2026-05-25T00:00:01Z",
                                "stage": "classpath",
                                "level": "INFO",
                                "message": "Executing Maven",
                            }
                        ],
                    },
                )
            # GET
            return _mock_response(
                200,
                {
                    "jobId": "job-1",
                    "status": "SUCCEEDED",
                    "stage": "complete",
                    "createdAt": "2026-05-25T00:00:00Z",
                    "finishedAt": "2026-05-25T00:00:02Z",
                    "events": [],
                },
            )

        mock_http.request.side_effect = _request_side_effect
        mock_get_client.return_value = mock_http

        submitted = await client.submit_analyze_job("/tmp/test-project")
        status = await client.get_analyze_job("job-1")

    assert submitted.job_id == "job-1"
    assert submitted.events[0].stage == "classpath"
    assert status.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_cancel_analyze_job_parses_status(client: WhiteboxClient) -> None:
    """验证取消接口（DELETE）请求与状态解析（O-04）。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = _mock_response(
            200,
            {
                "jobId": "job-1",
                "status": "CANCELLED",
                "stage": "cancelled",
                "createdAt": "2026-05-25T00:00:00Z",
                "events": [],
            },
        )
        mock_get_client.return_value = mock_http

        status = await client.cancel_analyze_job("job-1")

    assert status is not None
    assert status.job_id == "job-1"
    assert status.status == "CANCELLED"
    mock_http.request.assert_called_once()
    # DELETE /argus/api/analyze/jobs/{jobId}
    assert mock_http.request.call_args.args[0] == "DELETE"
    assert mock_http.request.call_args.args[1] == "/argus/api/analyze/jobs/job-1"


@pytest.mark.asyncio
async def test_cancel_analyze_job_returns_none_on_404(client: WhiteboxClient) -> None:
    """404（作业已过期 / 旧版 Java 无此端点）→ None，由调用方判定语义。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.request.return_value = _mock_response(404, {})
        mock_get_client.return_value = mock_http

        status = await client.cancel_analyze_job("gone")

    assert status is None
