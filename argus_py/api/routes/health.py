"""健康检查路由。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from argus_py.api.dependencies import get_event_bus, get_task_read_service, get_task_worker
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
async def readiness_check(request: Request) -> JSONResponse:
    """就绪探针：依据 lifespan 已初始化的容器状态依次检查 DB、事件总线、Worker。

    标准探针（K8s / Compose healthcheck）只依据 HTTP 状态码，因此未就绪时
    必须返回 **503** 而不是 200——否则探针会继续把未就绪实例判为可用并导流。
    进程尚未完成 lifespan 初始化（或已关闭）时同样返回 503；``/health``
    继续只表示进程存活，不做昂贵依赖检查。

    O-02：这里读取 ``app.state.container``（lifespan 启动时显式保存的容器），
    不通过 ``get_event_bus()`` / ``get_task_worker()`` 隐式创建依赖——容器没
    初始化成功时探针必须判未就绪，而不是"自愈式"地现场组装一份。
    """
    if not getattr(request.app.state, "lifespan_ready", False):
        return _readiness_body(
            503,
            ReadinessResponse(
                status="not_ready", db="not_ready", worker="not_ready", event_bus="not_ready"
            ),
        )

    container = getattr(request.app.state, "container", None)
    if container is None:
        # lifespan 未成功保存容器状态（非标准启动路径 / 异常初始化），不能就绪。
        return _readiness_body(
            503,
            ReadinessResponse(
                status="not_ready", db="not_ready", worker="not_ready", event_bus="not_ready"
            ),
        )

    db_status = await _check_db_cached()
    snapshot = container.task_worker.health_snapshot()
    worker_status = "ready" if (snapshot.is_started and snapshot.alive_loops > 0) else "not_ready"
    event_bus_status = (
        "ready"
        if container.event_bus is not None and container.event_bus.is_dispatchable()
        else "not_ready"
    )

    is_ready = db_status == "ready" and worker_status == "ready" and event_bus_status == "ready"
    return _readiness_body(
        200 if is_ready else 503,
        ReadinessResponse(
            status="ready" if is_ready else "not_ready",
            db=db_status,
            worker=worker_status,
            event_bus=event_bus_status,
        ),
    )


def _readiness_body(http_status: int, response: ReadinessResponse) -> JSONResponse:
    """构造 readiness 响应：未就绪时以 503 返回，便于探针识别。"""
    return JSONResponse(status_code=http_status, content=response.model_dump())


@router.get("/metrics", response_model=MetricsResponse)
async def metrics(
    worker: TaskWorker = Depends(get_task_worker),
) -> MetricsResponse:
    """返回运行指标（EventBus、队列、Worker 真实健康）。"""
    eb = get_event_bus()
    reader = get_task_read_service()

    qm = await worker.queue.metrics() if worker.queue else None
    if qm is None:
        running_tasks = 0
        queued_tasks = 0
        queue_capacity = 0
        queue_utilization = 0.0
        queue_oldest_age = -1.0
        queue_rejected = 0
    else:
        running_tasks = qm["active"]
        queued_tasks = qm["queued"]
        queue_capacity = qm["capacity"]
        queue_utilization = qm["utilization"]
        queue_oldest_age = qm["oldest_queued_age_seconds"]
        queue_rejected = qm["rejected_total"]

    io_stats = io_executor_stats()
    snapshot = worker.health_snapshot()
    last_consume_stale = (
        -1 if snapshot.last_consume_at is None else int(time.monotonic() - snapshot.last_consume_at)
    )
    return MetricsResponse(
        event_bus=eb.metrics() if eb else {},
        total_tasks=await run_in_thread(reader.count_tasks),
        running_tasks=running_tasks,
        queued_tasks=queued_tasks,
        worker_alive=snapshot.is_started and snapshot.alive_loops > 0,
        io_executor_queued=io_stats["queued"],
        worker_total_loops=snapshot.total_loops,
        worker_alive_loops=snapshot.alive_loops,
        worker_exited_loops=snapshot.exited_loops,
        worker_crashed_loops=snapshot.crashed_loops,
        worker_last_consume_stale_seconds=last_consume_stale,
        queue_capacity=queue_capacity,
        queue_utilization=queue_utilization,
        queue_oldest_queued_age_seconds=queue_oldest_age,
        queue_rejected_total=queue_rejected,
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
