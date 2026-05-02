"""健康检查路由。"""

from __future__ import annotations

from fastapi import APIRouter

from argus_py.api.schemas import HealthResponse
from argus_py.core.constants import PROJECT_NAME, PROJECT_VERSION

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """返回服务健康状态。"""
    return HealthResponse(status="healthy", version=PROJECT_VERSION, project=PROJECT_NAME)
