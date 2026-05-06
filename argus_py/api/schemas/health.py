"""健康检查 API Schema。"""

from __future__ import annotations

from argus_py.api.schemas.base import ApiModel


class HealthResponse(ApiModel):
    """健康检查响应。"""

    status: str
    version: str
    project: str
