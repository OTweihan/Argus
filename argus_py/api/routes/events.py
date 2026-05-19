"""任务时间线与 LLM 追踪 API 路由 — 只做 IO 适配 + API 序列化。"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from argus_py.api.dependencies import get_task_service
from argus_py.api.schemas.llm_trace import LLMTraceResponse
from argus_py.core.exceptions import TaskError
from argus_py.task.service import TaskService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["events"])


def _serialize_trace(record: dict[str, Any]) -> dict[str, Any]:
    """将原始 trace 记录通过 LLMTraceResponse 校验后转回 JSON 友好字典。"""
    return LLMTraceResponse.model_validate(record).model_dump(by_alias=True, mode="json")


@router.get("/{task_id}/events")
def list_task_events(
    task_id: str = Path(pattern=r"^task_[a-zA-Z0-9]+$"),
    service: TaskService = Depends(get_task_service),
):
    """返回任务的执行时间线事件（同步 SQLite 查询，线程池执行）。"""
    try:
        service.get_task(task_id)
    except TaskError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return service.list_timeline_events(task_id)


@router.get("/{task_id}/llm-traces")
def list_llm_traces(
    task_id: str = Path(pattern=r"^task_[a-zA-Z0-9]+$"),
    skip: int = 0,
    limit: int = 50,
    trace_id: str | None = None,
    service: TaskService = Depends(get_task_service),
):
    """返回任务的 LLM 调用追踪记录。"""
    try:
        service.get_task(task_id)
    except TaskError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    records = service.list_llm_traces(task_id, skip=skip, limit=limit, trace_id=trace_id)
    return [_serialize_trace(r) for r in records]


@router.get("/{task_id}/llm-traces/{trace_id}")
def get_trace_detail(
    task_id: str = Path(pattern=r"^task_[a-zA-Z0-9]+$"),
    trace_id: str = Path(pattern=r"^[a-zA-Z0-9_-]+$"),
    service: TaskService = Depends(get_task_service),
):
    """返回单条 LLM 调用的完整追踪记录。"""
    try:
        service.get_task(task_id)
    except TaskError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    record = service.get_llm_trace_detail(task_id, trace_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="追踪记录不存在")
    return _serialize_trace(record)


@router.get("/{task_id}/debug-bundle")
def download_debug_bundle(
    task_id: str = Path(pattern=r"^task_[a-zA-Z0-9]+$"),
    service: TaskService = Depends(get_task_service),
):
    """下载任务调试包（task.json + traces + 事件 + 截图）。"""
    try:
        task = service.get_task(task_id)
    except TaskError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    events = service.list_timeline_events(task_id)
    tmp_path = service.build_debug_bundle(task_id, task, events=events)

    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=f"debug-{task_id}.zip",
        headers={
            "Content-Disposition": f'attachment; filename="debug-{task_id}.zip"',
        },
        background=BackgroundTask(os.unlink, tmp_path),
    )
