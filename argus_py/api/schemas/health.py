"""健康检查 API Schema。"""

from __future__ import annotations

from argus_py.api.schemas.base import ApiModel


class HealthResponse(ApiModel):
    """健康检查响应。"""

    status: str
    version: str
    project: str


class ReadinessResponse(ApiModel):
    """就绪检查响应。"""

    status: str
    db: str
    worker: str
    event_bus: str


class MetricsResponse(ApiModel):
    """运行指标响应。"""

    event_bus: dict[str, int]
    total_tasks: int
    running_tasks: int
    queued_tasks: int
    worker_alive: bool
