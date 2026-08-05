"""阶段四：白盒真实 Java Analyzer E2E 测试。

标记: @pytest.mark.slow + @pytest.mark.e2e

需要：Maven 与 JDK 21+ 可用（与 scripts/dev.mjs 相同的环境要求）。
缺少 JAR 时自动执行 ``mvn -B package -DskipTests``（命令与 java_analyzer/Dockerfile
一致），产物为 ``java_analyzer/target/java-analyzer-*.jar``。自动构建失败时：
REQUIRE_JAVA_E2E=1 → FAILED；否则 → skipped。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import pytest

_REQUIRE_JAVA = os.environ.get("REQUIRE_JAVA_E2E", "0") == "1"
_JAVA_DIR = Path(__file__).parent.parent.parent / "java_analyzer"
_POM = _JAVA_DIR / "pom.xml"


def _find_java() -> str:
    """解析 Java 可执行文件：优先 JAVA_HOME，其次 PATH。

    与 scripts/dev.mjs 一致：运行 Java Analyzer 应使用与 Maven 构建相同的 JDK。
    Windows 上 PATH 中的 java 可能是 Oracle javapath stub，会解析到错误的 JRE，
    因此不能直接依赖 PATH。
    """
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("java")
    if found:
        return found
    return "java"


def _find_jar() -> Path | None:
    target_dir = _JAVA_DIR / "target"
    if not target_dir.exists():
        return None
    jars = sorted(target_dir.glob("java-analyzer-*.jar"))
    return jars[-1] if jars else None


def _build_jar() -> Path | None:
    """缺 JAR 时自动执行 Maven package（命令与 Dockerfile Stage 1 一致）。"""
    mvn = shutil.which("mvn")
    if mvn is None:
        print("未找到 Maven（mvn 不在 PATH 中），无法自动构建 Java Analyzer。")
        return None
    print(f"未找到 Java Analyzer JAR，正在自动构建：{mvn} -f {_POM} -B package -DskipTests …")
    try:
        result = subprocess.run(
            [mvn, "-f", str(_POM), "-B", "package", "-DskipTests"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        print("Maven 构建超时（600s），已放弃自动构建。")
        return None
    if result.returncode != 0:
        # 仅保留构建输出尾部，避免刷屏
        tail = result.stdout[-2000:].strip()
        print(f"Maven 构建失败（exit={result.returncode}）：\n{tail}")
        return None
    print("Maven 构建完成。")
    return _find_jar()


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(url: str, timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            # trust_env=False：请求是本地 Java 进程，不得经过系统代理
            # （Windows 系统代理会对 127.0.0.1 返回 502）。
            r = httpx.get(f"{url}/actuator/health", timeout=2, trust_env=False)
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
        jar = _build_jar()
    if jar is None:
        if _REQUIRE_JAVA:
            pytest.fail("Java Analyzer JAR not found and REQUIRE_JAVA_E2E=1")
        pytest.skip("Java Analyzer JAR not found")

    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [_find_java(), "-jar", str(jar), f"--server.port={port}"],
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
