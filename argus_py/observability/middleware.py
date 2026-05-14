"""HTTP 请求日志中间件。"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from argus_py.observability.context import bind_context, new_request_id
from argus_py.observability.events import STATUS_ERROR, STATUS_SUCCESS, log_event
from argus_py.observability.redaction import redact

logger = logging.getLogger("argus.request")
EVENT_HTTP_REQUEST = "http.request"

# 默认降噪路径：精确匹配
DEFAULT_QUIET_PATHS: frozenset[str] = frozenset({"/healthz", "/", "/favicon.ico"})
# 默认降噪前缀：静态资源、SPA 资源目录
DEFAULT_QUIET_PREFIXES: tuple[str, ...] = ("/assets/", "/static/")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """为每个 HTTP 请求生成 request_id 并记录结构化访问日志。

    匹配 ``quiet_paths`` / ``quiet_prefixes`` 的请求会被降级为 DEBUG，
    避免健康检查、静态资源等高频访问刷屏。错误请求（5xx / 异常）始终
    维持原级别。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        quiet_paths: Iterable[str] | None = None,
        quiet_prefixes: Iterable[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._quiet_paths: frozenset[str] = (
            frozenset(quiet_paths) if quiet_paths is not None else DEFAULT_QUIET_PATHS
        )
        self._quiet_prefixes: tuple[str, ...] = (
            tuple(quiet_prefixes) if quiet_prefixes is not None else DEFAULT_QUIET_PREFIXES
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or new_request_id()
        started = perf_counter()
        with bind_context(request_id=request_id, operation=EVENT_HTTP_REQUEST):
            try:
                response = await call_next(request)
            except Exception:
                duration_ms = round((perf_counter() - started) * 1000, 2)
                http = _http_payload(request, None)
                log_event(
                    logger,
                    EVENT_HTTP_REQUEST,
                    status=STATUS_ERROR,
                    duration_ms=duration_ms,
                    http=http,
                    message=f"HTTP 请求异常：{_request_summary(http, duration_ms, request_id)}",
                    level=logging.ERROR,
                    exc_info=True,
                )
                raise
            duration_ms = round((perf_counter() - started) * 1000, 2)
            response.headers["X-Request-ID"] = request_id
            http = _http_payload(request, response.status_code)
            level = self._resolve_level(request.url.path, response.status_code)
            status_text = STATUS_SUCCESS if response.status_code < 500 else STATUS_ERROR
            log_event(
                logger,
                EVENT_HTTP_REQUEST,
                status=status_text,
                duration_ms=duration_ms,
                http=http,
                message=f"HTTP 请求完成：{_request_summary(http, duration_ms, request_id)}",
                level=level,
            )
            return response

    def _resolve_level(self, path: str, status_code: int) -> int:
        """4xx/5xx 不降级；命中静默规则的成功响应降为 DEBUG。"""
        if status_code >= 400:
            return logging.INFO
        if path in self._quiet_paths:
            return logging.DEBUG
        if any(path.startswith(prefix) for prefix in self._quiet_prefixes):
            return logging.DEBUG
        return logging.INFO


def _http_payload(request: Request, status_code: int | None) -> dict[str, object]:
    return {
        "method": request.method,
        "path": request.url.path,
        "query": redact(dict(request.query_params.multi_items())),
        "statusCode": status_code,
        "client": request.client.host if request.client else None,
    }


def _request_summary(http: dict[str, object], duration_ms: float, request_id: str) -> str:
    query = http.get("query")
    query_text = f" query={query}" if query else ""
    return (
        f"{http.get('method')} {http.get('path')}"
        f"{query_text} status={http.get('statusCode')}"
        f" durationMs={duration_ms:g}"
        f" client={http.get('client')}"
        f" requestId={request_id}"
    )
