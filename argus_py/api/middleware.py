"""FastAPI 中间件和异常处理。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

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
from argus_py.utils.logger import get_logger

logger = get_logger(__name__)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """P0-5：基于 ``Content-Length`` 拦截超大请求 body。

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
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        {"limitBytes": self._max_bytes, "receivedBytes": size},
                    )
        return await call_next(request)


def configure_middleware(app: FastAPI, settings: ServerSettings) -> None:
    """注册跨域配置和统一异常响应。"""
    if settings.observability_request_logging:
        app.add_middleware(RequestLoggingMiddleware)

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

    # P0-6：用 isinstance 判断具体 NotFound 子类，替代不可靠的
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
            status.HTTP_422_UNPROCESSABLE_ENTITY,
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
    return JSONResponse(
        status_code=http_status,
        content=jsonable_encoder(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details or {},
                }
            }
        ),
    )
