"""健康检查路由。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from argus_py.api.dependencies import get_event_bus, get_task_query_service, get_task_worker
from argus_py.api.schemas import HealthResponse, MetricsResponse, ReadinessResponse
from argus_py.core.constants import PROJECT_NAME, PROJECT_VERSION
from argus_py.infra.db import DEFAULT_DB_PATH, connect
from argus_py.infra.worker import TaskWorker
from argus_py.observability.context import io_executor_stats, run_in_thread

router = APIRouter(tags=["health"])

# DB 连通性检查缓存，避免 K8s 高频探针反复创建 SQLite 连接。
_db_last_check: float = 0.0
_db_last_status: str = "not_ready"
_DB_CACHE_TTL = 5.0


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """返回服务存活状态。"""
    return HealthResponse(status="healthy", version=PROJECT_VERSION, project=PROJECT_NAME)


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(worker: TaskWorker = Depends(get_task_worker)) -> ReadinessResponse:
    """就绪探针：依次检查 DB、事件总线、Worker。"""
    db_status = await _check_db_cached()
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

    io_stats = io_executor_stats()
    return MetricsResponse(
        event_bus=eb.metrics() if eb else {},
        total_tasks=await run_in_thread(query_svc.count_tasks),
        running_tasks=running_tasks,
        queued_tasks=queued_tasks,
        worker_alive=worker.is_started,
        io_executor_queued=io_stats["queued"],
    )


async def _check_db_cached() -> str:
    """带 5s TTL 缓存的 DB 连通性检查，避免 K8s 高频探针竞争 SQLite 锁。"""
    global _db_last_check, _db_last_status
    now = time.monotonic()
    if now - _db_last_check < _DB_CACHE_TTL:
        return _db_last_status
    _db_last_check = now
    _db_last_status = await run_in_thread(_ping_db)
    return _db_last_status


def _ping_db() -> str:
    """同步 DB 存活检测。"""
    try:
        conn = connect(DEFAULT_DB_PATH)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return "ready"
    except Exception:
        return "not_ready"
