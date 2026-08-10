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
    io_executor_queued: int = -1
    # O-02：Worker 真实健康（loop 级）。worker_alive 仅表示"是否在消费"，
    # 无法体现部分 loop 异常退出；以下字段给出完整快照，供监控定位。
    worker_total_loops: int = 0
    worker_alive_loops: int = 0
    worker_exited_loops: int = 0
    worker_crashed_loops: int = 0
    # 距最近一次实际消费任务经过的秒数；-1 表示启动后从未消费过任务。
    worker_last_consume_stale_seconds: int = -1
    # O-03：任务队列容量与压力。utilization = queued ÷ capacity（0 = 无界为 0）；
    # oldest_queued_age 无排队时为 -1；rejected_total 累计满载拒绝次数。
    queue_capacity: int = 0
    queue_utilization: float = 0.0
    queue_oldest_queued_age_seconds: float = -1.0
    queue_rejected_total: int = 0
