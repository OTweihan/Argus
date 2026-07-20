"""FastAPI 中间件和异常处理。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from argus_py.api.rate_limit import (
    RateLimitMiddleware,
    TokenBucketLimiter,
    build_rules,
)
from argus_py.config.server_settings import ServerSettings
from argus_py.core.exceptions import (
    ArgusError,
    ModelConfigError,
    ModelConfigNotFoundError,
    ProjectError,
    ProjectNotFoundError,
    TaskError,
    TaskNotFoundError,
)
from argus_py.observability.middleware import RequestLoggingMiddleware

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """注入基础安全响应头。

    私网部署同样需要这些防护：
    - ``X-Content-Type-Options: nosniff`` 防止浏览器把响应误识别为可执行类型，
      杜绝 MIME 注入。
    - ``X-Frame-Options: DENY`` 防 clickjacking（内部其他后台把 Argus 嵌入
      iframe 进行 UI 欺诈）。
    - ``Referrer-Policy: no-referrer`` 避免把内部 URL/任务 ID 通过 Referer
      泄露到外链域名。
    - ``Cross-Origin-Opener-Policy: same-origin`` 阻止跨源 window 引用，
      与 ``X-Frame-Options`` 形成纵深防御。

    暂不加 CSP：FastAPI ``/docs`` 的 Swagger UI 加载 CDN，Element Plus 大量
    使用 inline 样式，加严格 CSP 会破坏；如未来需要可针对前端静态目录单独
    挂中间件，避开 ``/docs`` 与 ``/api`` 路径。
    """

    _DEFAULTS: dict[str, str] = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Opener-Policy": "same-origin",
    }

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        for header, value in self._DEFAULTS.items():
            response.headers.setdefault(header, value)
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """基于 ``Content-Length`` 拦截超大请求 body。

    两层拦截策略：
    1. 优先信任客户端 ``Content-Length`` 头：声明值已超限直接 413，避免读取流。
    2. 没有 ``Content-Length``（chunked transfer）时仍允许通过；进一步的硬限制由
       下游 ASGI server / 反向代理负责。我们在这里不做流式累加是因为 Starlette
       BaseHTTPMiddleware 缓冲整个 body 后才回调，再做累加意义不大。

    ``max_bytes`` <= 0 表示禁用。
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if self._max_bytes > 0:
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    size = int(content_length)
                except ValueError:
                    size = -1
                if size > self._max_bytes:
                    return _error_response(
                        "REQUEST_TOO_LARGE",
                        f"请求体超出限制 {self._max_bytes} 字节。",
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        {"limitBytes": self._max_bytes, "receivedBytes": size},
                    )
        return await call_next(request)


def configure_middleware(app: FastAPI, settings: ServerSettings) -> None:
    """注册跨域配置和统一异常响应。"""
    if settings.observability_request_logging:
        app.add_middleware(RequestLoggingMiddleware)

    # SecurityHeaders 放在最早 add：Starlette 中间件按反向注册顺序构造责任链，
    # 越早 add 越靠近响应出口，可保证所有路由响应都注入安全头（含 StaticFiles
    # 和异常响应）。
    app.add_middleware(SecurityHeadersMiddleware)

    # body 大小限制要在 CORS / 业务路由之前生效，所以在这里先 add（Starlette 是
    # 反向注册顺序，越晚 add 越接近 ASGI 入口；body 限制要最早拦，所以放最后 add）。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )
    if settings.request_max_body_size_bytes > 0:
        app.add_middleware(
            BodySizeLimitMiddleware,
            max_bytes=settings.request_max_body_size_bytes,
        )

    # 限流放在 body 限制之后（即责任链上"更内"的位置）：先放行明显超大的请求
    # 节省 token 桶资源；同时 429 响应不会被 SecurityHeaders 漏掉（它在更外层）。
    if settings.rate_limit_enabled:
        rules = build_rules(settings.rate_limit_routes)
        if rules:
            limiter = TokenBucketLimiter()
            app.state.rate_limiter = limiter
            app.add_middleware(
                RateLimitMiddleware,
                limiter=limiter,
                rules=rules,
                trust_forwarded=settings.rate_limit_trust_forwarded,
            )
            logger.info(
                "限流已启用：rules=%d trust_forwarded=%s",
                len(rules),
                settings.rate_limit_trust_forwarded,
            )
        else:
            logger.warning("rate_limit.enabled=true 但 routes 为空，限流已跳过")

    # 用 isinstance 判断具体 NotFound 子类，替代不可靠的
    # ``"not found" in message`` 字符串匹配。子类继承自基类，注册顺序无关；
    # 只要 raise 时用 ``TaskNotFoundError`` 等，handler 就会走 404 分支。
    @app.exception_handler(TaskError)
    async def handle_task_error(_: Request, exc: TaskError) -> JSONResponse:
        if isinstance(exc, TaskNotFoundError):
            return _error_response("TASK_NOT_FOUND", str(exc), status.HTTP_404_NOT_FOUND)
        return _error_response("TASK_ERROR", str(exc), status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(ProjectError)
    async def handle_project_error(_: Request, exc: ProjectError) -> JSONResponse:
        if isinstance(exc, ProjectNotFoundError):
            return _error_response("PROJECT_NOT_FOUND", str(exc), status.HTTP_404_NOT_FOUND)
        return _error_response("PROJECT_ERROR", str(exc), status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(ModelConfigError)
    async def handle_model_config_error(_: Request, exc: ModelConfigError) -> JSONResponse:
        if isinstance(exc, ModelConfigNotFoundError):
            return _error_response("MODEL_CONFIG_NOT_FOUND", str(exc), status.HTTP_404_NOT_FOUND)
        return _error_response("MODEL_CONFIG_ERROR", str(exc), status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(ArgusError)
    async def handle_argus_error(_: Request, exc: ArgusError) -> JSONResponse:
        return _error_response("ARGUS_ERROR", str(exc), status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            "INVALID_REQUEST",
            "请求参数无效。",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"errors": exc.errors()},
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            code = str(detail.get("code") or "HTTP_ERROR")
            message = str(detail.get("message") or detail)
            details: dict[str, Any] = dict(detail.get("details") or {})
        else:
            code = "HTTP_ERROR"
            message = str(detail)
            details = {}
        return _error_response(code, message, exc.status_code, details)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "未捕获的 API 异常：%s %s",
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return _error_response(
            "INTERNAL_SERVER_ERROR",
            "服务内部错误。",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _error_response(
    code: str,
    message: str,
    http_status: int,
    details: dict | None = None,
) -> JSONResponse:
    """生成统一错误响应。"""
    from argus_py.api.errors import error_response

    return error_response(code, message, http_status, details)
