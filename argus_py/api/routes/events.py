"""任务时间线与 LLM 追踪 API 路由 — 只做 IO 适配 + API 序列化。"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from argus_py.api.dependencies import get_task_query_service, get_task_timeline_service
from argus_py.api.params import TaskIdPath
from argus_py.api.schemas.llm_trace import LLMTraceResponse
from argus_py.core.exceptions import TaskError
from argus_py.observability.context import run_in_thread
from argus_py.task.event import TaskTimelineService
from argus_py.task.query import TaskQueryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["events"])


def _serialize_trace(record: dict[str, Any]) -> dict[str, Any]:
    """将原始 trace 记录通过 LLMTraceResponse 校验后转回 JSON 友好字典。"""
    return LLMTraceResponse.model_validate(record).model_dump(by_alias=True, mode="json")


@router.get("/{task_id}/events")
async def list_task_events(
    task_id: TaskIdPath,
    query: TaskQueryService = Depends(get_task_query_service),
    timeline: TaskTimelineService = Depends(get_task_timeline_service),
):
    """返回任务的执行时间线事件。"""
    try:
        await run_in_thread(query.get_task, task_id)
    except TaskError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    events = await run_in_thread(timeline.list_by_task, task_id)
    return [e.to_dict() for e in events]


@router.get("/{task_id}/llm-traces")
async def list_llm_traces(
    task_id: TaskIdPath,
    skip: int = 0,
    limit: int = 50,
    trace_id: str | None = None,
    query: TaskQueryService = Depends(get_task_query_service),
):
    """返回任务的 LLM 调用追踪记录。"""
    try:
        await run_in_thread(query.get_task, task_id)
    except TaskError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    records = await run_in_thread(query.list_llm_traces, task_id, skip, limit, trace_id)
    return [_serialize_trace(r) for r in records]


@router.get("/{task_id}/llm-traces/{trace_id}")
async def get_trace_detail(
    task_id: TaskIdPath,
    trace_id: str = Path(pattern=r"^[a-zA-Z0-9_-]+$"),
    query: TaskQueryService = Depends(get_task_query_service),
):
    """返回单条 LLM 调用的完整追踪记录。"""
    try:
        await run_in_thread(query.get_task, task_id)
    except TaskError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    record = await run_in_thread(query.get_llm_trace_detail, task_id, trace_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="追踪记录不存在")
    return _serialize_trace(record)


@router.get("/{task_id}/debug-bundle")
async def download_debug_bundle(
    task_id: TaskIdPath,
    query: TaskQueryService = Depends(get_task_query_service),
    timeline: TaskTimelineService = Depends(get_task_timeline_service),
):
    """下载任务调试包（task.json + traces + 事件 + 截图）。"""
    try:
        task = await run_in_thread(query.get_task, task_id)
    except TaskError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    events = await run_in_thread(timeline.list_by_task, task_id)
    events_dicts = [e.to_dict() for e in events]
    tmp_path = await run_in_thread(query.build_debug_bundle, task_id, task, events_dicts)

    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=f"debug-{task_id}.zip",
        headers={
            "Content-Disposition": f'attachment; filename="debug-{task_id}.zip"',
        },
        background=BackgroundTask(os.unlink, tmp_path),
    )
