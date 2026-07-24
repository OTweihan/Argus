"""Java 白盒分析子模块 HTTP 客户端。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

from argus_py.whitebox.models import WhiteboxJobStatus, WhiteboxResult

logger = logging.getLogger(__name__)


# ── 异常层级 ─────────────────────────────────────────────────────────────────


class WhiteboxClientError(Exception):
    """白盒分析客户端错误基类。"""


class WhiteboxTransientError(WhiteboxClientError):
    """瞬时错误：可重试。

    涵盖：connect timeout、read timeout、429、500、502、503、504。
    """


class WhiteboxPermanentError(WhiteboxClientError):
    """永久错误：不应重试。

    涵盖：401、403、非 2xx 且非瞬时错误、协议不兼容。
    """


class WhiteboxJobNotFoundError(WhiteboxPermanentError):
    """404 — 作业不存在。"""


class WhiteboxAuthenticationError(WhiteboxPermanentError):
    """401/403 — 认证错误。"""


class WhiteboxResultNotReadyError(WhiteboxTransientError):
    """409 on result — 结果尚未就绪。"""


class WhiteboxIdempotencyConflictError(WhiteboxPermanentError):
    """409 on submit — 相同 clientRequestId 但参数不同。"""


TRANSIENT_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


# ── 可见性校验结果 ──────────────────────────────────────────────────────────


class VisibilityStatus(StrEnum):
    VALIDATED = "validated"
    ENDPOINT_UNSUPPORTED = "endpoint_unsupported"
    ANALYZER_UNAVAILABLE = "analyzer_unavailable"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True)
class SourceVisibilityResult:
    """Java 源码可见性校验的机器可判定结果。"""

    status: VisibilityStatus
    exists: bool | None = None
    readable: bool | None = None
    reason: str | None = None


# ── 请求/响应工具 ────────────────────────────────────────────────────────────


def _response_json(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise WhiteboxClientError(f"{operation} 响应不是有效 JSON: {response.text[:500]}") from exc
    if not isinstance(data, dict):
        raise WhiteboxClientError(f"{operation} 响应结构不是对象。")
    return data


def _parse_response(response: httpx.Response, operation: str, parser: Any) -> Any:
    data = _response_json(response, operation)
    try:
        return parser(data)
    except (TypeError, ValueError, KeyError) as exc:
        raise WhiteboxClientError(f"{operation} 响应解析失败: {exc}") from exc


# ── 客户端 ───────────────────────────────────────────────────────────────────


class WhiteboxClient:
    """Java 分析服务的异步 HTTP 客户端。

    Parameters
    ----------
    base_url : str
        Java 分析服务的基础 URL，格式如 ``http://host:port``。
    request_timeout : float
        单次 HTTP 请求超时秒数，默认 30。
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8081",
        request_timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._request_timeout = request_timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def request_timeout(self) -> float:
        """单次 HTTP 请求超时秒数。"""
        return self._request_timeout

    async def _get_client(self) -> httpx.AsyncClient:
        """懒初始化 httpx 客户端。"""
        if self._client is None:
            limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
            transport = httpx.AsyncHTTPTransport(limits=limits)
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._request_timeout,
                limits=limits,
                transport=transport,
            )
        return self._client

    # ── 统一请求分发 ──────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        allowed_statuses: frozenset[int] = frozenset(),
        timeout: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """统一请求方法，将 httpx 异常映射为 typed error。

        Parameters
        ----------
        allowed_statuses : frozenset[int]
            这些状态码不会被映射为异常，由调用方自行解释语义。
        timeout : float | None
            单次请求超时；为 None 时使用客户端默认值。
        """
        effective_timeout = timeout if timeout is not None else self._request_timeout
        try:
            client = await self._get_client()
            response = await client.request(method, path, timeout=effective_timeout, **kwargs)
        except httpx.TimeoutException as exc:
            raise WhiteboxTransientError(f"请求超时: {method} {path}") from exc
        except httpx.ConnectError as exc:
            raise WhiteboxTransientError(f"连接失败: {method} {path}") from exc
        except httpx.RequestError as exc:
            raise WhiteboxTransientError(f"请求失败: {method} {path}: {exc}") from exc

        # allowed_statuses 不做异常映射
        if response.status_code in allowed_statuses:
            return response

        if response.status_code in TRANSIENT_STATUS_CODES:
            raise WhiteboxTransientError(f"服务端瞬时错误 {response.status_code}: {method} {path}")
        if response.status_code == 404:
            raise WhiteboxJobNotFoundError(f"不存在: {method} {path}")
        if response.status_code in (401, 403):
            raise WhiteboxAuthenticationError(f"认证失败 {response.status_code}: {method} {path}")
        if not response.is_success:
            raise WhiteboxPermanentError(
                f"请求失败 {response.status_code}: {method} {path}: {response.text[:500]}"
            )
        return response

    # ── 分析接口 ──────────────────────────────────────────────────────────

    async def analyze(
        self,
        source_path: str,
        scope: str = "all",
        maven: dict | None = None,
        target_modules: list[str] | None = None,
    ) -> WhiteboxResult:
        """向 Java 分析服务发起**同步**分析请求（兼容旧接口）。"""
        payload: dict[str, object] = {"sourcePath": source_path, "scope": scope}
        if maven:
            payload["maven"] = maven
        if target_modules:
            payload["targetModules"] = target_modules

        # 同步 analyze 使用较长超时
        try:
            response = await self._request(
                "POST", "/argus/api/analyze", json=payload, timeout=300.0
            )
        except WhiteboxTransientError as exc:
            raise WhiteboxClientError(f"白盒分析请求失败: {exc}") from exc
        return _parse_response(response, "白盒分析", WhiteboxResult.from_dict)

    # ── 异步作业接口 ──────────────────────────────────────────────────────

    async def submit_analyze_job(
        self,
        source_path: str,
        scope: str = "all",
        maven: dict | None = None,
        target_modules: list[str] | None = None,
        client_request_id: str | None = None,
    ) -> WhiteboxJobStatus:
        """提交异步 Java 分析作业。

        Parameters
        ----------
        client_request_id : str | None
            幂等键。相同 client_request_id 返回已有作业。
        """
        payload: dict[str, object] = {"sourcePath": source_path, "scope": scope}
        if maven:
            payload["maven"] = maven
        if target_modules:
            payload["targetModules"] = target_modules
        if client_request_id:
            payload["clientRequestId"] = client_request_id

        try:
            response = await self._request(
                "POST",
                "/argus/api/analyze/jobs",
                json=payload,
                allowed_statuses=frozenset({409}),
            )
        except WhiteboxPermanentError:
            raise
        except WhiteboxClientError:
            raise

        if response.status_code == 409:
            raise WhiteboxIdempotencyConflictError(
                f"相同 clientRequestId 但参数不同: {client_request_id}"
            )

        return _parse_response(response, "Java 分析作业提交", WhiteboxJobStatus.from_dict)

    async def get_analyze_job(
        self,
        job_id: str,
        timeout: float | None = None,
    ) -> WhiteboxJobStatus:
        """查询异步 Java 分析作业状态。

        Parameters
        ----------
        timeout : float | None
            单次请求超时，为 None 时使用默认值。
        """
        try:
            response = await self._request(
                "GET", f"/argus/api/analyze/jobs/{job_id}", timeout=timeout
            )
        except WhiteboxJobNotFoundError as exc:
            raise WhiteboxTaskError(f"远端作业 {job_id} 不存在") from exc
        return _parse_response(response, "Java 分析作业查询", WhiteboxJobStatus.from_dict)

    async def get_analyze_job_result(
        self,
        job_id: str,
        timeout: float | None = None,
    ) -> WhiteboxResult:
        """获取已完成异步 Java 分析作业的结果。

        Parameters
        ----------
        timeout : float | None
            单次请求超时。
        """
        try:
            response = await self._request(
                "GET",
                f"/argus/api/analyze/jobs/{job_id}/result",
                timeout=timeout,
                allowed_statuses=frozenset({409}),
            )
        except WhiteboxJobNotFoundError as exc:
            raise WhiteboxTaskError(f"远端作业 {job_id} 不存在") from exc

        if response.status_code == 409:
            raise WhiteboxResultNotReadyError(f"结果尚未就绪: job_id={job_id}")

        return _parse_response(response, "Java 分析作业结果获取", WhiteboxResult.from_dict)

    # ── 取消 ──────────────────────────────────────────────────────────────

    async def cancel_job(self, job_id: str) -> dict:
        """best-effort 取消 Java 分析作业。"""
        try:
            response = await self._request(
                "DELETE",
                f"/argus/api/analyze/jobs/{job_id}",
                allowed_statuses=frozenset({404}),
            )
        except WhiteboxJobNotFoundError:
            return {"jobId": job_id, "status": "UNKNOWN", "cancelled": False}
        except WhiteboxAuthenticationError:
            logger.error("取消作业 %s 失败: 认证错误", job_id)
            return {"jobId": job_id, "status": "UNKNOWN", "cancelled": False}
        except WhiteboxTransientError:
            logger.warning("取消作业 %s 失败（瞬时错误）", job_id, exc_info=True)
            return {"jobId": job_id, "status": "UNKNOWN", "cancelled": False}
        except WhiteboxClientError:
            logger.warning("取消作业 %s 失败", job_id, exc_info=True)
            return {"jobId": job_id, "status": "UNKNOWN", "cancelled": False}

        if response.status_code == 404:
            return {"jobId": job_id, "status": "UNKNOWN", "cancelled": False}

        try:
            return response.json()
        except ValueError:
            return {"jobId": job_id, "status": "UNKNOWN", "cancelled": False}

    # ── 可见性校验 ────────────────────────────────────────────────────────

    async def validate_source(self, source_path: str) -> SourceVisibilityResult:
        """验证 Java 分析器能否读取指定的源码路径。

        Returns
        -------
        SourceVisibilityResult
            机器可判定的验证结果。调用方据此决定阻断或降级。
        """
        try:
            response = await self._request(
                "POST",
                "/argus/api/analyze/validate-source",
                json={"sourcePath": source_path},
                timeout=15.0,
                allowed_statuses=frozenset({404, 501}),
            )
        except WhiteboxTransientError as exc:
            return SourceVisibilityResult(
                status=VisibilityStatus.ANALYZER_UNAVAILABLE,
                reason=str(exc),
            )
        except WhiteboxPermanentError as exc:
            return SourceVisibilityResult(
                status=VisibilityStatus.INVALID_RESPONSE,
                reason=str(exc),
            )

        # 端点不支持（旧版本 Java）
        if response.status_code in (404, 501):
            return SourceVisibilityResult(
                status=VisibilityStatus.ENDPOINT_UNSUPPORTED,
                reason=f"Java 不支持此端点 (status={response.status_code})",
            )

        # 解析响应
        try:
            data = response.json()
        except ValueError:
            return SourceVisibilityResult(
                status=VisibilityStatus.INVALID_RESPONSE,
                reason="Java 返回了非 JSON 响应",
            )

        if not isinstance(data, dict):
            return SourceVisibilityResult(
                status=VisibilityStatus.INVALID_RESPONSE,
                reason="响应格式非预期",
            )

        exists = data.get("exists")
        readable = data.get("readable")
        if not isinstance(exists, bool) or not isinstance(readable, bool):
            return SourceVisibilityResult(
                status=VisibilityStatus.INVALID_RESPONSE,
                reason="响应字段格式非预期",
            )

        return SourceVisibilityResult(
            status=VisibilityStatus.VALIDATED,
            exists=exists,
            readable=readable,
        )

    # ── 健康检查 ──────────────────────────────────────────────────────────

    async def health(self) -> bool:
        """检查 Java 分析服务健康状态。"""
        try:
            client = await self._get_client()
            response = await client.get("/actuator/health")
            return response.status_code == 200
        except Exception:
            logger.debug("白盒分析服务健康检查失败", exc_info=True)
            return False

    # ── 生命周期 ──────────────────────────────────────────────────────────

    async def close(self) -> None:
        """关闭 HTTP 客户端（别名，兼容旧代码）。"""
        await self.aclose()

    async def aclose(self) -> None:
        """关闭 HTTP 客户端。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> WhiteboxClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()


# 避免循环导入
from argus_py.whitebox.exceptions import WhiteboxTaskError  # noqa: E402
