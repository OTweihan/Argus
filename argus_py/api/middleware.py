"""FastAPI 中间件和异常处理。"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from argus_py.api.dependencies import ServerSettings
from argus_py.core.exceptions import ArgusError, ModelConfigError, ProjectError, TaskError
from argus_py.utils.logger import get_logger

logger = get_logger(__name__)


def configure_middleware(app: FastAPI, settings: ServerSettings) -> None:
    """注册跨域配置和统一异常响应。"""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    @app.exception_handler(TaskError)
    async def handle_task_error(_: Request, exc: TaskError) -> JSONResponse:
        message = str(exc)
        code = "TASK_NOT_FOUND" if "not found" in message.lower() else "TASK_ERROR"
        http_status = (
            status.HTTP_404_NOT_FOUND if code == "TASK_NOT_FOUND" else status.HTTP_400_BAD_REQUEST
        )
        return _error_response(code, message, http_status)

    @app.exception_handler(ProjectError)
    async def handle_project_error(_: Request, exc: ProjectError) -> JSONResponse:
        message = str(exc)
        code = "PROJECT_NOT_FOUND" if "not found" in message.lower() else "PROJECT_ERROR"
        http_status = (
            status.HTTP_404_NOT_FOUND
            if code == "PROJECT_NOT_FOUND"
            else status.HTTP_400_BAD_REQUEST
        )
        return _error_response(code, message, http_status)

    @app.exception_handler(ModelConfigError)
    async def handle_model_config_error(_: Request, exc: ModelConfigError) -> JSONResponse:
        message = str(exc)
        code = "MODEL_CONFIG_NOT_FOUND" if "not found" in message.lower() else "MODEL_CONFIG_ERROR"
        http_status = (
            status.HTTP_404_NOT_FOUND
            if code == "MODEL_CONFIG_NOT_FOUND"
            else status.HTTP_400_BAD_REQUEST
        )
        return _error_response(code, message, http_status)

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
            details = dict(detail.get("details") or {})
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
