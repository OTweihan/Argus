"""任务 REST API 路由 — 只做参数/响应转换，业务编排委托 TaskApplicationService。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from argus_py.api.dependencies import get_task_app_service
from argus_py.api.schemas import (
    InferredLimitsResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskStartResponse,
    TaskSummaryListResponse,
    TaskSummaryResponse,
    TaskUpdateRequest,
)
from argus_py.core.enums import TaskStatus
from argus_py.task.application import TaskAppError, TaskApplicationService
from argus_py.task.strategy import infer_execution_limits

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _call(
    fn: Any,
    *args: Any,
    http_status: int = 409,
    **kwargs: Any,
) -> Any:
    """调用同步应用层方法，TaskAppError 自动转为 HTTPException。"""
    try:
        return fn(*args, **kwargs)
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
    params = app.resolve_create_params(
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
    task = _call(app.create_task, **params)
    return TaskResponse.from_task(task)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    request: TaskUpdateRequest,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """更新待执行任务的基础信息。"""
    params = app.resolve_create_params(
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
    task_id: str,
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
    tasks = app.list_task_summaries(
        status=status, project_id=project_id, offset=offset, limit=limit, q=q
    )
    total = app.count_tasks(status=status, project_id=project_id, q=q)
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


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """查询任务详情。"""
    task, sched = await app.get_task_with_scheduler(task_id)
    return TaskResponse.from_task(task, scheduler_status=sched)


@router.post("/{task_id}/start", response_model=TaskStartResponse)
async def start_task(
    task_id: str,
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
    task_id: str,
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
    task_id: str,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """取消任务。支持 pending、queued 和 running 状态。"""
    task, sched = await _acall(app.cancel_task, task_id)
    return TaskResponse.from_task(task, scheduler_status=sched)


@router.post("/{task_id}/pause", response_model=TaskResponse)
async def pause_task(
    task_id: str,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """暂停运行中的任务。"""
    task = await _acall(app.pause_task, task_id)
    return TaskResponse.from_task(task)


@router.post("/{task_id}/resume", response_model=TaskResponse)
async def resume_task(
    task_id: str,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """恢复暂停的任务。"""
    task = await _acall(app.resume_task, task_id)
    return TaskResponse.from_task(task)


@router.post("/{task_id}/stop", response_model=TaskResponse)
async def stop_task(
    task_id: str,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """强制终止任务。"""
    task, sched = await _acall(app.stop_task, task_id)
    return TaskResponse.from_task(task, scheduler_status=sched)
