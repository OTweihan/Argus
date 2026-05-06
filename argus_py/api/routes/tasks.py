"""任务 REST API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from argus_py.api.dependencies import (
    get_model_config_service,
    get_project_service,
    get_task_queue,
    get_task_service,
)
from argus_py.api.schemas import TaskCreateRequest, TaskListResponse, TaskResponse, TaskStartResponse
from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import TaskError
from argus_py.infra.queue import TaskQueue
from argus_py.config.service import ModelConfigService
from argus_py.project.service import ProjectService
from argus_py.task.service import TaskService
from argus_py.task.strategy import resolve_execution_limits

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    request: TaskCreateRequest,
    service: TaskService = Depends(get_task_service),
    project_service: ProjectService = Depends(get_project_service),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
) -> TaskResponse:
    """创建任务快照，不立即启动执行。"""
    project = project_service.get_project(request.project_id)
    start_url = request.start_url or project.base_url
    if not start_url:
        raise TaskError("创建任务需要 startUrl，或项目需要配置 baseUrl。")

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
    task = service.create_task(
        goal=request.goal,
        start_url=start_url,
        task_type=request.task_type,
        project_id=project.project_id,
        max_steps=limits.max_steps,
        timeout_seconds=limits.timeout_seconds,
        capture_screenshots=capture_screenshots,
        parameters=parameters,
    )
    return TaskResponse.from_task(task)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status: TaskStatus | None = None,
    project_id: str | None = Query(default=None, alias="projectId"),
    limit: int = Query(default=50, gt=0, le=200),
    service: TaskService = Depends(get_task_service),
    queue: TaskQueue = Depends(get_task_queue),
) -> TaskListResponse:
    """列出任务，支持按状态和项目过滤。"""
    all_tasks = service.list_tasks(status=status, project_id=project_id)
    tasks = all_tasks[:limit]
    responses = []
    for task in tasks:
        responses.append(
            TaskResponse.from_task(
                task,
                scheduler_status=await queue.scheduler_status(task.task_id),
            )
        )
    return TaskListResponse(total=len(all_tasks), tasks=responses)


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
    """取消尚未完成的任务。"""
    await queue.cancel(task_id)
    task = service.cancel_task(task_id)
    return TaskResponse.from_task(
        task,
        scheduler_status=await queue.scheduler_status(task.task_id),
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
    """暂停任务占位；暂停语义需要 T012/T013 的执行中断和事件机制。"""
    task = service.get_task(task_id)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "TASK_PAUSE_NOT_SUPPORTED",
            "message": "暂停任务需要执行循环中断点和事件总线，当前阶段暂不支持。",
            "details": {"taskId": task.task_id, "status": task.status.value},
        },
    )


@router.post("/{task_id}/stop", response_model=TaskResponse)
async def stop_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
    queue: TaskQueue = Depends(get_task_queue),
) -> TaskResponse:
    """终止任务；pending/queued 任务直接取消，running 中断后续实现。"""
    task = service.get_task(task_id)
    scheduler_status = await queue.scheduler_status(task.task_id)
    if scheduler_status == "queued":
        await queue.cancel(task.task_id)
        cancelled = service.cancel_task(task)
        return TaskResponse.from_task(
            cancelled,
            scheduler_status=await queue.scheduler_status(cancelled.task_id),
        )
    if task.status is TaskStatus.PENDING:
        return TaskResponse.from_task(service.cancel_task(task))
    if task.status is TaskStatus.RUNNING or scheduler_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TASK_STOP_NOT_SUPPORTED",
                "message": "运行中任务当前不支持可靠中断。",
                "details": {
                    "taskId": task.task_id,
                    "status": task.status.value,
                    "schedulerStatus": scheduler_status,
                },
            },
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "TASK_ALREADY_FINISHED",
            "message": f"任务已处于终态，不能终止：{task.status.value}。",
            "details": {"taskId": task.task_id, "status": task.status.value},
        },
    )
