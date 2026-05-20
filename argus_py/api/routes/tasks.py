"""任务 REST API 路由 — 只做参数/响应转换，业务编排委托 TaskApplicationService。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from argus_py.api.dependencies import get_task_app_service
from argus_py.api.params import TaskIdPath
from argus_py.api.schemas import (
    DashboardStatsResponse,
    InferredLimitsResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskStartResponse,
    TaskSummaryListResponse,
    TaskSummaryResponse,
    TaskUpdateRequest,
)
from argus_py.core.enums import TaskStatus
from argus_py.observability.context import run_in_thread
from argus_py.task.application import TaskAppError, TaskApplicationService
from argus_py.task.strategy import infer_execution_limits

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _acall_sync(
    fn: Any,
    *args: Any,
    http_status: int = 409,
    **kwargs: Any,
) -> Any:
    """在线程池中调用同步应用层方法，TaskAppError 自动转为 HTTPException。

    ``asyncio.to_thread`` 把阻塞 SQLite / 文件 IO 移出事件循环，避免并发请求
    互相阻塞。``TaskAppError`` 通过 ``to_thread`` 在线程内抛出，由 ``await`` 处
    重新抛到协程上下文，再被本函数转换。``http_status`` 参数为兼容旧 ``_call``
    签名保留，未实际使用（HTTP 状态码以 ``TaskAppError.http_status`` 为准）。
    """
    del http_status  # 保留参数以兼容旧调用签名，实际未使用
    try:
        return await run_in_thread(fn, *args, **kwargs)
    except TaskAppError as e:
        raise HTTPException(
            status_code=e.http_status,
            detail=e.to_http_detail(),
        )


async def _acall(
    fn: Any,
    *args: Any,
    http_status: int = 409,
    **kwargs: Any,
) -> Any:
    """调用异步应用层方法，TaskAppError 自动转为 HTTPException。"""
    del http_status
    try:
        return await fn(*args, **kwargs)
    except TaskAppError as e:
        raise HTTPException(
            status_code=e.http_status,
            detail=e.to_http_detail(),
        )


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    request: TaskCreateRequest,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """创建任务快照，不立即启动执行。"""
    # resolve_create_params 内部读取 project + model_config（同步 SQLite），
    # 与 create_task 一起放线程池执行，避免事件循环被任一阶段阻塞。
    params = await run_in_thread(
        app.resolve_create_params,
        goal=request.goal,
        name=request.name,
        start_url=request.start_url,
        task_type=request.task_type,
        project_id=request.project_id,
        max_steps=request.max_steps,
        timeout_seconds=request.timeout_seconds,
        capture_screenshots=request.capture_screenshots,
        model_config_id=request.model_config_id,
        parameters=request.parameters,
    )
    task = await _acall_sync(app.create_task, **params)
    return TaskResponse.from_task(task)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    request: TaskUpdateRequest,
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """更新待执行任务的基础信息。"""
    params = await run_in_thread(
        app.resolve_create_params,
        goal=request.goal,
        name=request.name,
        start_url=request.start_url,
        task_type=request.task_type,
        project_id=request.project_id,
        max_steps=request.max_steps,
        timeout_seconds=request.timeout_seconds,
        capture_screenshots=request.capture_screenshots,
        model_config_id=request.model_config_id,
        parameters=request.parameters,
    )
    updated, sched = await _acall(app.update_task, task_id, params)
    return TaskResponse.from_task(updated, scheduler_status=sched)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> Response:
    """删除未启动的 pending 任务。"""
    await _acall(app.delete_task, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=TaskSummaryListResponse)
async def list_tasks(
    status: TaskStatus | None = None,
    project_id: str | None = Query(default=None, alias="projectId"),
    q: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, gt=0, le=200),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskSummaryListResponse:
    """列出任务（轻量，不含日志和发现项），支持过滤和分页。"""
    # 单 SQL 语句同时返回列表与总量：COUNT(*) OVER() 窗口函数避免
    # 两次往返，也不必再走 count_tasks。
    tasks, total = await run_in_thread(
        app.list_task_summaries,
        status=status,
        project_id=project_id,
        offset=offset,
        limit=limit,
        q=q,
    )
    status_snapshot = await app.snapshot_queue_statuses()
    return TaskSummaryListResponse(
        total=total,
        tasks=[
            TaskSummaryResponse.from_task(task, scheduler_status=status_snapshot.get(task.task_id))
            for task in tasks
        ],
    )


@router.get("/infer-limits", response_model=InferredLimitsResponse)
async def infer_limits(
    goal: str = Query(..., min_length=1),
    start_url: str | None = Query(default=None),
) -> InferredLimitsResponse:
    """根据任务目标和起始 URL 推断推荐的最大步数和超时时间。"""
    limits = infer_execution_limits(goal, start_url or "")
    return InferredLimitsResponse(
        max_steps=limits.max_steps,
        timeout_seconds=limits.timeout_seconds,
    )


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    recent_limit: int = Query(default=8, ge=1, le=50, alias="recentLimit"),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> DashboardStatsResponse:
    """返回仪表盘聚合统计。

    与分页列表解耦：COUNT 走 SQLite 索引，避免 dashboard 把"当前页"误当全量。
    """
    stats_or_err: Any
    status_snapshot_or_err: Any
    stats_or_err, status_snapshot_or_err = await asyncio.gather(
        run_in_thread(app.get_dashboard_stats, recent_limit=recent_limit),
        app.snapshot_queue_statuses(),
        return_exceptions=True,
    )
    if isinstance(stats_or_err, Exception):
        raise stats_or_err
    stats = stats_or_err
    status_snapshot: dict[str, str] = (
        {} if isinstance(status_snapshot_or_err, Exception) else status_snapshot_or_err
    )
    return DashboardStatsResponse(
        tasks_total=stats["tasks_total"],
        running_total=stats["running_total"],
        findings_total=stats["findings_total"],
        recent_tasks=[
            TaskSummaryResponse.from_task(task, scheduler_status=status_snapshot.get(task.task_id))
            for task in stats["recent_tasks"]
        ],
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """查询任务详情。"""
    task, sched = await app.get_task_with_scheduler(task_id)
    return TaskResponse.from_task(task, scheduler_status=sched)


@router.post("/{task_id}/start", response_model=TaskStartResponse)
async def start_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskStartResponse:
    """将 pending 任务加入后台执行队列。"""
    task, sched = await _acall(app.start_task, task_id)
    return TaskStartResponse(
        scheduler_status=sched,
        task=TaskResponse.from_task(task, scheduler_status=sched),
    )


@router.post("/{task_id}/restart", response_model=TaskStartResponse)
async def restart_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskStartResponse:
    """重试失败/超时/取消的任务，创建新任务并立即入队。"""
    task, sched = await _acall(app.restart_task, task_id)
    return TaskStartResponse(
        scheduler_status=sched,
        task=TaskResponse.from_task(task, scheduler_status=sched),
    )


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """取消任务。支持 pending、queued 和 running 状态。"""
    task, sched = await _acall(app.cancel_task, task_id)
    return TaskResponse.from_task(task, scheduler_status=sched)


@router.post("/{task_id}/pause", response_model=TaskResponse)
async def pause_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """暂停运行中的任务。"""
    task = await _acall(app.pause_task, task_id)
    return TaskResponse.from_task(task)


@router.post("/{task_id}/resume", response_model=TaskResponse)
async def resume_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """恢复暂停的任务。"""
    task = await _acall(app.resume_task, task_id)
    return TaskResponse.from_task(task)
