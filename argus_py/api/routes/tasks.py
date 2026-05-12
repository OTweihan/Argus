"""任务 REST API 路由。"""

from __future__ import annotations

from typing import Any, TypedDict

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from argus_py.api.dependencies import (
    get_model_config_service,
    get_project_service,
    get_task_queue,
    get_task_service,
)
from argus_py.api.schemas import (
    InferredLimitsResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskStartResponse,
    TaskSummaryListResponse,
    TaskSummaryResponse,
    TaskUpdateRequest,
)
from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.infra.queue import TaskQueue
from argus_py.project.service import ProjectService
from argus_py.task.service import TaskService
from argus_py.task.strategy import infer_execution_limits, resolve_execution_limits

router = APIRouter(prefix="/tasks", tags=["tasks"])


class _TaskResolvedParams(TypedDict):
    """_resolve_task_params 返回的结构化参数。"""

    goal: str
    name: str | None
    start_url: str | None
    task_type: TaskType
    project_id: str | None
    max_steps: int
    timeout_seconds: int
    capture_screenshots: bool
    parameters: dict[str, Any]


def _resolve_task_params(
    request: TaskCreateRequest,
    project_service: ProjectService,
    model_config_service: ModelConfigService,
) -> _TaskResolvedParams:
    """解析任务参数，合并项目默认值。"""
    project = project_service.get_project(request.project_id)
    start_url = request.start_url or project.base_url
    if not start_url:
        raise TaskError("任务需要 startUrl，或项目需要配置 baseUrl。")

    max_steps = request.max_steps or project.default_max_steps
    timeout_seconds = request.timeout_seconds or project.default_timeout_seconds
    capture_screenshots = (
        request.capture_screenshots
        if request.capture_screenshots is not None
        else project.default_capture_screenshots
    )
    parameters = {**project.parameters, **request.parameters}
    if request.model_config_id:
        model_config_service.get_model_config(request.model_config_id)
        parameters["modelConfigId"] = request.model_config_id

    limits = resolve_execution_limits(
        request.goal,
        start_url,
        max_steps,
        timeout_seconds,
    )

    return {
        "goal": request.goal,
        "name": request.name,
        "start_url": start_url,
        "task_type": request.task_type,
        "project_id": project.project_id,
        "max_steps": limits.max_steps,
        "timeout_seconds": limits.timeout_seconds,
        "capture_screenshots": capture_screenshots,
        "parameters": parameters,
    }


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    request: TaskCreateRequest,
    service: TaskService = Depends(get_task_service),
    project_service: ProjectService = Depends(get_project_service),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
) -> TaskResponse:
    """创建任务快照，不立即启动执行。"""
    params = _resolve_task_params(request, project_service, model_config_service)
    task = service.create_task(**params)
    return TaskResponse.from_task(task)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    request: TaskUpdateRequest,
    service: TaskService = Depends(get_task_service),
    project_service: ProjectService = Depends(get_project_service),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
    queue: TaskQueue = Depends(get_task_queue),
) -> TaskResponse:
    """更新待执行任务的基础信息。"""
    task = service.get_task(task_id)
    scheduler_status = await queue.scheduler_status(task_id)
    if task.status is not TaskStatus.PENDING or scheduler_status is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TASK_NOT_EDITABLE",
                "message": f"只有 pending 且未入队的任务可以编辑，当前状态：{task.status.value}。",
                "details": {
                    "taskId": task_id,
                    "status": task.status.value,
                    "schedulerStatus": scheduler_status,
                },
            },
        )

    params = _resolve_task_params(request, project_service, model_config_service)
    updated = service.update_task_info(task, **params)
    return TaskResponse.from_task(
        updated,
        scheduler_status=await queue.scheduler_status(updated.task_id),
    )


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
    queue: TaskQueue = Depends(get_task_queue),
) -> Response:
    """删除未启动的 pending 任务。"""
    task = service.get_task(task_id)
    scheduler_status = await queue.scheduler_status(task_id)
    if task.status is not TaskStatus.PENDING or scheduler_status is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TASK_NOT_DELETABLE",
                "message": f"只有 pending 且未入队的任务可以删除，当前状态：{task.status.value}。",
                "details": {
                    "taskId": task_id,
                    "status": task.status.value,
                    "schedulerStatus": scheduler_status,
                },
            },
        )
    service.delete_pending_task(task)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=TaskSummaryListResponse)
async def list_tasks(
    status: TaskStatus | None = None,
    project_id: str | None = Query(default=None, alias="projectId"),
    q: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, gt=0, le=200),
    service: TaskService = Depends(get_task_service),
    queue: TaskQueue = Depends(get_task_queue),
) -> TaskSummaryListResponse:
    """列出任务（轻量，不含日志和发现项），支持按状态、项目和关键词过滤及分页。"""
    tasks = service.list_task_summaries(
        status=status, project_id=project_id, offset=offset, limit=limit, q=q
    )
    total = service.count_tasks(status=status, project_id=project_id, q=q)
    status_snapshot = await queue.snapshot_statuses()
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
    service: TaskService = Depends(get_task_service),
    queue: TaskQueue = Depends(get_task_queue),
) -> TaskResponse:
    """查询任务详情。"""
    task = service.get_task(task_id)
    return TaskResponse.from_task(
        task,
        scheduler_status=await queue.scheduler_status(task.task_id),
    )


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
    queue: TaskQueue = Depends(get_task_queue),
) -> TaskResponse:
    """取消任务。支持 pending、queued 和 running 状态。"""
    task = service.get_task(task_id)
    scheduler_status = await queue.scheduler_status(task_id)

    if scheduler_status == "queued":
        await queue.cancel(task_id)

    if task.status in (
        TaskStatus.CANCELLED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "TASK_ALREADY_FINISHED",
                "message": f"任务已处于终态，不能取消：{task.status.value}。",
                "details": {"taskId": task_id, "status": task.status.value},
            },
        )

    task = service.cancel_task(task)
    return TaskResponse.from_task(
        task,
        scheduler_status=await queue.scheduler_status(task.task_id),
    )


@router.post("/{task_id}/restart", response_model=TaskStartResponse)
async def restart_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
    queue: TaskQueue = Depends(get_task_queue),
) -> TaskStartResponse:
    """重试失败/超时/取消的任务，创建新任务并立即入队。"""
    task = service.get_task(task_id)
    if task.status not in (
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.CANCELLED,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TASK_NOT_RETRYABLE",
                "message": f"只有失败/超时/取消的任务可以重试，当前状态：{task.status.value}。",
                "details": {"taskId": task.task_id, "status": task.status.value},
            },
        )
    new_task = service.restart_task(task)
    try:
        result = await queue.enqueue(new_task.task_id)
    except Exception:
        service.delete_pending_task(new_task)
        raise
    if result.already_known:
        service.delete_pending_task(new_task)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TASK_ALREADY_SCHEDULED",
                "message": f"新创建的任务意外处于已调度状态：{result.scheduler_status}。",
                "details": {"taskId": new_task.task_id, "schedulerStatus": result.scheduler_status},
            },
        )
    return TaskStartResponse(
        scheduler_status=result.scheduler_status,
        task=TaskResponse.from_task(new_task, scheduler_status=result.scheduler_status),
    )


@router.post("/{task_id}/start", response_model=TaskStartResponse)
async def start_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
    queue: TaskQueue = Depends(get_task_queue),
) -> TaskStartResponse:
    """将 pending 任务加入后台执行队列。"""
    task = service.get_task(task_id)
    if task.status is not TaskStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TASK_NOT_PENDING",
                "message": f"只有 pending 任务可以启动，当前状态：{task.status.value}。",
                "details": {"taskId": task.task_id, "status": task.status.value},
            },
        )
    result = await queue.enqueue(task.task_id)
    if result.already_known:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TASK_ALREADY_SCHEDULED",
                "message": f"任务已处于调度状态：{result.scheduler_status}。",
                "details": {"taskId": task.task_id, "schedulerStatus": result.scheduler_status},
            },
        )
    return TaskStartResponse(
        scheduler_status=result.scheduler_status,
        task=TaskResponse.from_task(task, scheduler_status=result.scheduler_status),
    )


@router.post("/{task_id}/pause", response_model=TaskResponse)
async def pause_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    """暂停运行中的任务。执行循环通过 CancellationToken 检测暂停信号并等待。"""
    task = service.get_task(task_id)
    if task.status is not TaskStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TASK_NOT_RUNNING",
                "message": f"只有运行中的任务可以暂停，当前状态：{task.status.value}。",
                "details": {"taskId": task.task_id, "status": task.status.value},
            },
        )
    task = service.pause_task(task)
    return TaskResponse.from_task(task)


@router.post("/{task_id}/resume", response_model=TaskResponse)
async def resume_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    """恢复暂停的任务。通过 CancellationToken 唤醒等待中的执行循环。"""
    task = service.get_task(task_id)
    if task.status is not TaskStatus.PAUSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TASK_NOT_PAUSED",
                "message": f"只有暂停的任务可以恢复，当前状态：{task.status.value}。",
                "details": {"taskId": task.task_id, "status": task.status.value},
            },
        )
    task = service.resume_task(task)
    return TaskResponse.from_task(task)


@router.post("/{task_id}/stop", response_model=TaskResponse)
async def stop_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
    queue: TaskQueue = Depends(get_task_queue),
) -> TaskResponse:
    """强制终止任务。pending/queued 从队列移除；running 通过信号量中断。"""
    task = service.get_task(task_id)
    scheduler_status = await queue.scheduler_status(task.task_id)

    if scheduler_status == "queued":
        await queue.cancel(task_id)

    if task.status in (
        TaskStatus.CANCELLED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "TASK_ALREADY_FINISHED",
                "message": f"任务已处于终态，不能终止：{task.status.value}。",
                "details": {"taskId": task_id, "status": task.status.value},
            },
        )

    task = service.cancel_task(task)
    return TaskResponse.from_task(
        task,
        scheduler_status=await queue.scheduler_status(task.task_id),
    )
