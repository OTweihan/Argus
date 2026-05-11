"""HTTP 请求日志中间件。"""

from __future__ import annotations

import logging
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from argus_py.observability.context import bind_context, new_request_id
from argus_py.observability.redaction import redact

logger = logging.getLogger("argus.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """为每个 HTTP 请求生成 request_id 并记录结构化访问日志。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or new_request_id()
        started = perf_counter()
        with bind_context(request_id=request_id, operation="http.request"):
            try:
                response = await call_next(request)
            except Exception:
                duration_ms = round((perf_counter() - started) * 1000, 2)
                http = _http_payload(request, None)
                logger.exception(
                    "HTTP 请求异常：%s",
                    _request_summary(http, duration_ms, request_id),
                    extra={
                        "event": "http.request",
                        "status": "error",
                        "duration_ms": duration_ms,
                        "http": http,
                    },
                )
                raise
            duration_ms = round((perf_counter() - started) * 1000, 2)
            response.headers["X-Request-ID"] = request_id
            http = _http_payload(request, response.status_code)
            logger.info(
                "HTTP 请求完成：%s",
                _request_summary(http, duration_ms, request_id),
                extra={
                    "event": "http.request",
                    "status": "success" if response.status_code < 500 else "error",
                    "duration_ms": duration_ms,
                    "http": http,
                },
            )
            return response


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
