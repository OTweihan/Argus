"""Java 白盒分析子模块 HTTP 客户端。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from argus_py.whitebox.models import WhiteboxJobStatus, WhiteboxResult

logger = logging.getLogger(__name__)


class WhiteboxClientError(Exception):
    """白盒分析客户端错误。"""


class WhiteboxClient:
    """Java 分析服务的异步 HTTP 客户端。

    Parameters
    ----------
    base_url : str
        Java 分析服务的基础 URL，格式如 ``http://host:port``。
    timeout : float
        请求超时秒数，默认 300（Java 分析可能耗时较长）。
    max_retries : int
        最大重试次数，默认 3。
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8081",
        timeout: float = 300.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """懒初始化 httpx 客户端。"""
        if self._client is None:
            limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
            transport = httpx.AsyncHTTPTransport(limits=limits)
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                limits=limits,
                transport=transport,
            )
        return self._client

    async def analyze(
        self,
        source_path: str,
        scope: str = "all",
        maven: dict | None = None,
        target_modules: list[str] | None = None,
    ) -> WhiteboxResult:
        """向 Java 分析服务发起分析请求。

        Parameters
        ----------
        source_path : str
            本地源码目录路径。
        scope : str
            分析范围：``"endpoints"`` | ``"callgraph"`` | ``"all"``。
        maven : dict | None
            Maven 配置字典，可选字段：autoDetect, generateClasspath,
            classpathFile, executable, settingsXml, localRepository, offline。
        target_modules : list[str] | None
            Maven 目标模块，可传 artifactId 或相对路径，如 ``han-modules/han-admin``。

        Returns
        -------
        WhiteboxResult
            分析结果包含端点清单、调用图和代码缺陷。

        Raises
        ------
        WhiteboxClientError
            连接失败、服务错误或重试耗尽。
        """
        payload: dict[str, object] = {"sourcePath": source_path, "scope": scope}
        if maven:
            payload["maven"] = maven
        if target_modules:
            payload["targetModules"] = target_modules
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                client = await self._get_client()
                response = await client.post("/argus/api/analyze", json=payload)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
                return WhiteboxResult.from_dict(data)

            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning("白盒分析请求超时（第 %d 次）: %s", attempt, exc)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                body = exc.response.text[:500]
                logger.error("白盒分析服务返回错误 %d: %s", status, body)
                raise WhiteboxClientError(f"Java 分析服务返回 {status}: {body}") from exc
            except httpx.RequestError as exc:
                last_error = exc
                logger.warning("白盒分析请求失败（第 %d 次）: %s", attempt, exc)

            if attempt < self._max_retries:
                wait = 2 ** (attempt - 1)
                await asyncio.sleep(wait)

        raise WhiteboxClientError(
            f"白盒分析请求在 {self._max_retries} 次重试后仍失败: {last_error}"
        ) from last_error

    async def submit_analyze_job(
        self,
        source_path: str,
        scope: str = "all",
        maven: dict | None = None,
        target_modules: list[str] | None = None,
    ) -> WhiteboxJobStatus:
        """提交异步 Java 分析作业。"""
        payload: dict[str, object] = {"sourcePath": source_path, "scope": scope}
        if maven:
            payload["maven"] = maven
        if target_modules:
            payload["targetModules"] = target_modules

        try:
            client = await self._get_client()
            response = await client.post("/argus/api/analyze/jobs", json=payload)
            response.raise_for_status()
            return WhiteboxJobStatus.from_dict(response.json())
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:500]
            raise WhiteboxClientError(f"Java 分析作业提交失败 {status}: {body}") from exc
        except httpx.RequestError as exc:
            raise WhiteboxClientError(f"Java 分析作业提交失败: {exc}") from exc

    async def get_analyze_job(self, job_id: str) -> WhiteboxJobStatus:
        """查询异步 Java 分析作业状态。"""
        try:
            client = await self._get_client()
            response = await client.get(f"/argus/api/analyze/jobs/{job_id}")
            response.raise_for_status()
            return WhiteboxJobStatus.from_dict(response.json())
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:500]
            raise WhiteboxClientError(f"Java 分析作业查询失败 {status}: {body}") from exc
        except httpx.RequestError as exc:
            raise WhiteboxClientError(f"Java 分析作业查询失败: {exc}") from exc

    async def get_analyze_job_result(self, job_id: str) -> WhiteboxResult:
        """获取已完成异步 Java 分析作业的结果。"""
        try:
            client = await self._get_client()
            response = await client.get(f"/argus/api/analyze/jobs/{job_id}/result")
            response.raise_for_status()
            return WhiteboxResult.from_dict(response.json())
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:500]
            raise WhiteboxClientError(f"Java 分析作业结果获取失败 {status}: {body}") from exc
        except httpx.RequestError as exc:
            raise WhiteboxClientError(f"Java 分析作业结果获取失败: {exc}") from exc

    async def health(self) -> bool:
        """检查 Java 分析服务健康状态。"""
        try:
            client = await self._get_client()
            response = await client.get("/actuator/health")
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """关闭 HTTP 客户端。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> WhiteboxClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
