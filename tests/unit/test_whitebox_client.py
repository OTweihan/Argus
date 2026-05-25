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


@pytest.fixture(scope="module")
def client() -> WhiteboxClient:
    return WhiteboxClient(base_url="http://test-host:8081", timeout=10, max_retries=1)


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
        mock_http.post.return_value = _mock_response(200, mock_response_data)
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


@pytest.mark.asyncio
async def test_analyze_empty_response(client: WhiteboxClient) -> None:
    """验证空结果的正确处理。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post.return_value = _mock_response(
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
        mock_http.post.return_value = _mock_response(
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
async def test_analyze_http_error(client: WhiteboxClient) -> None:
    """验证 HTTP 错误时抛出 WhiteboxClientError。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        err_resp = _mock_response(400, {})
        request = httpx.Request("POST", "http://test-host:8081/argus/api/analyze")
        err_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=request, response=httpx.Response(400, request=request)
        )
        mock_http.post.return_value = err_resp
        mock_get_client.return_value = mock_http

        with pytest.raises(WhiteboxClientError):
            await client.analyze("/tmp/test-project")


@pytest.mark.asyncio
async def test_analyze_retry_then_fail(client: WhiteboxClient) -> None:
    """验证重试耗尽后抛出 WhiteboxClientError。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post.side_effect = httpx.ConnectError("Connection refused")
        mock_get_client.return_value = mock_http

        with pytest.raises(WhiteboxClientError):
            await client.analyze("/tmp/test-project")

    assert mock_http.post.call_count == client._max_retries


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
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.get.side_effect = ConnectionError("refused")
        mock_get_client.return_value = mock_http

        assert await client.health() is False


@pytest.mark.asyncio
async def test_analyze_scope_callgraph(client: WhiteboxClient) -> None:
    """验证 scope 参数正确传递。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post.return_value = _mock_response(
            200, {"endpoints": [], "callGraph": {}, "findings": []}
        )
        mock_get_client.return_value = mock_http

        await client.analyze(
            "/tmp/test", scope="callgraph", target_modules=["han-modules/han-admin"]
        )

        call_kwargs = mock_http.post.call_args.kwargs
        assert call_kwargs["json"]["scope"] == "callgraph"
        assert call_kwargs["json"]["targetModules"] == ["han-modules/han-admin"]


@pytest.mark.asyncio
async def test_submit_and_query_analyze_job(client: WhiteboxClient) -> None:
    """验证异步作业接口请求和状态解析。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post.return_value = _mock_response(
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
        mock_http.get.return_value = _mock_response(
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
        mock_get_client.return_value = mock_http

        submitted = await client.submit_analyze_job("/tmp/test-project")
        status = await client.get_analyze_job("job-1")

    assert submitted.job_id == "job-1"
    assert submitted.events[0].stage == "classpath"
    assert status.status == "SUCCEEDED"
