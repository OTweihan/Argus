"""API 错误响应公共构建器。"""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def error_payload(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建统一的错误响应 JSON 结构。

    所有 API 错误响应均使用此格式：
    ``{"error": {"code": ..., "message": ..., "details": ...}}``
    """
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }


def error_response(
    code: str,
    message: str,
    http_status: int,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """构建 FastAPI JSONResponse 错误响应。"""
    return JSONResponse(
        status_code=http_status,
        content=jsonable_encoder(error_payload(code, message, details)),
        headers=headers,
    )
