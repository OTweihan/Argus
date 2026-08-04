"""阶段四：白盒真实 Java Analyzer E2E 测试。

标记: @pytest.mark.slow + @pytest.mark.e2e

需要：Java Analyzer JAR 已构建、JDK 21+ 可用。
环境变量 REQUIRE_JAVA_E2E=1 时启动失败视为 FAILED；
REQUIRE_JAVA_E2E=0（默认）时跳过。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import pytest

_REQUIRE_JAVA = os.environ.get("REQUIRE_JAVA_E2E", "0") == "1"


def _find_jar() -> Path | None:
    java_dir = Path(__file__).parent.parent.parent / "java_analyzer" / "target"
    if not java_dir.exists():
        return None
    jars = sorted(java_dir.glob("argus-analyzer-*.jar"))
    return jars[-1] if jars else None


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(url: str, timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{url}/actuator/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def java_analyzer_url():
    """启动 Java Analyzer 进程，返回 base_url。"""
    jar = _find_jar()
    if jar is None:
        if _REQUIRE_JAVA:
            pytest.fail("Java Analyzer JAR not found and REQUIRE_JAVA_E2E=1")
        pytest.skip("Java Analyzer JAR not found")

    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        ["java", "-jar", str(jar), f"--server.port={port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_health(base_url):
            proc.terminate()
            proc.wait(timeout=10)
            if _REQUIRE_JAVA:
                pytest.fail("Java Analyzer health check failed")
            pytest.skip("Java Analyzer health check failed")
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.slow
@pytest.mark.e2e
class TestWhiteboxRealAnalyzer:
    @pytest.mark.asyncio
    async def test_direct_analyze_pipeline(self, java_analyzer_url: str) -> None:
        """临时源码 → client.analyze() 一次请求完成 → 验证 endpoints。"""
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp) / "src"
            src_dir.mkdir()
            (src_dir / "HelloController.java").write_text(
                """package test;
import org.springframework.web.bind.annotation.*;
@RestController
public class HelloController {
    @GetMapping("/hello")
    public String hello() { return "Hello"; }
}
""",
                encoding="utf-8",
            )

            from argus_py.whitebox.client import WhiteboxClient

            client = WhiteboxClient(base_url=java_analyzer_url, request_timeout=30)
            result = await client.analyze(str(tmp), scope="endpoints")

            assert result is not None
            assert len(result.endpoints) > 0
            assert result.endpoints[0].path == "/hello"

    @pytest.mark.asyncio
    async def test_async_job_pipeline(self, java_analyzer_url: str) -> None:
        """临时源码 → 异步 submit → 轮询 → get_result() 验证最终结果。

        P1 回归：之前只轮询到 SUCCEEDED 就结束，没有调用 get_result()
        验证实际分析结果内容，导致 result 端点回归无法发现。
        """
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp) / "src"
            src_dir.mkdir()
            (src_dir / "HelloController.java").write_text(
                """package test;
import org.springframework.web.bind.annotation.*;
@RestController
public class HelloController {
    @GetMapping("/hello")
    public String hello() { return "Hello"; }
}
""",
                encoding="utf-8",
            )

            from argus_py.whitebox.client import WhiteboxClient

            client = WhiteboxClient(base_url=java_analyzer_url, request_timeout=30)

            submitted = await client.submit_analyze_job(str(tmp), scope="endpoints")
            assert submitted is not None
            assert submitted.job_id

            # 轮询
            deadline = time.monotonic() + 60
            final_status = None
            while time.monotonic() < deadline:
                final_status = await client.get_analyze_job(submitted.job_id)
                if final_status.status in ("SUCCEEDED", "FAILED"):
                    break
                await asyncio.sleep(2)

            assert final_status is not None
            assert final_status.status == "SUCCEEDED"

            # P1 修复：获取并验证最终结果
            result = await client.get_analyze_job_result(submitted.job_id)
            assert result is not None
            assert len(result.endpoints) > 0
            assert any(ep.path == "/hello" for ep in result.endpoints)
