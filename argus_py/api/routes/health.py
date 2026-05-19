"""健康检查路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from argus_py.api.dependencies import get_event_bus, get_task_query_service, get_task_worker
from argus_py.api.schemas import HealthResponse, MetricsResponse, ReadinessResponse
from argus_py.core.constants import PROJECT_NAME, PROJECT_VERSION
from argus_py.infra.db import DEFAULT_DB_PATH, connect
from argus_py.infra.worker import TaskWorker

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """返回服务存活状态。"""
    return HealthResponse(status="healthy", version=PROJECT_VERSION, project=PROJECT_NAME)


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(worker: TaskWorker = Depends(get_task_worker)) -> ReadinessResponse:
    """就绪探针：依次检查 DB、事件总线、Worker。"""
    db_status = _check_db()
    worker_status = "ready" if worker.is_started else "not_ready"
    eb = get_event_bus()
    event_bus_status = "ready" if eb is not None else "not_ready"

    is_ready = db_status == "ready" and worker_status == "ready" and event_bus_status == "ready"
    return ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        db=db_status,
        worker=worker_status,
        event_bus=event_bus_status,
    )


@router.get("/metrics", response_model=MetricsResponse)
async def metrics(
    worker: TaskWorker = Depends(get_task_worker),
) -> MetricsResponse:
    """返回运行指标（EventBus、队列、Worker）。"""
    eb = get_event_bus()
    query_svc = get_task_query_service()

    counts = await worker.queue.counts() if worker.queue else {"queued": 0, "active": 0}
    running_tasks = counts["active"]
    queued_tasks = counts["queued"]

    return MetricsResponse(
        event_bus=eb.metrics() if eb else {},
        total_tasks=query_svc.count_tasks(),
        running_tasks=running_tasks,
        queued_tasks=queued_tasks,
        worker_alive=worker.is_started,
    )


def _check_db() -> str:
    """检查 SQLite 连通性。"""
    try:
        conn = connect(DEFAULT_DB_PATH)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return "ready"
    except Exception:
        return "not_ready"
