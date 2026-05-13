"""任务时间线与 LLM 追踪 API 路由。"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from argus_py.api.dependencies import get_task_service
from argus_py.core.paths import OUTPUT_DIR, SCREENSHOTS_DIR
from argus_py.task.service import TaskService

router = APIRouter(prefix="/tasks", tags=["events"])


@router.get("/{task_id}/events")
async def list_task_events(
    task_id: str,
    service: TaskService = Depends(get_task_service),
):
    """返回任务的执行时间线事件。"""
    try:
        service.get_task(task_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return service.list_timeline_events(task_id)


@router.get("/{task_id}/llm-traces")
async def list_llm_traces(
    task_id: str,
    service: TaskService = Depends(get_task_service),
):
    """返回任务的 LLM 调用追踪记录（从 JSONL 文件读取）。"""
    try:
        service.get_task(task_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    trace_path = OUTPUT_DIR / "traces" / f"{task_id}.jsonl"
    if not trace_path.exists():
        return []
    records: list[dict] = []
    with open(trace_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


@router.get("/{task_id}/llm-traces/{trace_id}")
async def get_trace_detail(
    task_id: str,
    trace_id: str,
    service: TaskService = Depends(get_task_service),
):
    """返回单条 LLM 调用的完整追踪记录。"""
    try:
        service.get_task(task_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    trace_path = OUTPUT_DIR / "traces" / f"{task_id}.jsonl"
    if not trace_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="追踪记录不存在")
    with open(trace_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("trace_id") == trace_id:
                return record
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="追踪记录不存在")


@router.get("/{task_id}/debug-bundle")
async def download_debug_bundle(
    task_id: str,
    service: TaskService = Depends(get_task_service),
):
    """下载任务调试包（task.json + traces + 事件 + 截图）。"""
    try:
        task = service.get_task(task_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # task.json
        from argus_py.utils.jsonx import to_jsonable

        zf.writestr("task.json", json.dumps(to_jsonable(task), ensure_ascii=False, indent=2))

        # traces/llm.jsonl
        trace_path = OUTPUT_DIR / "traces" / f"{task_id}.jsonl"
        if trace_path.exists():
            zf.write(trace_path, "traces/llm.jsonl")

        # traces/events.jsonl
        events = service.list_timeline_events(task_id)
        if events:
            events_jsonl = "\n".join(json.dumps(e, ensure_ascii=False) for e in events)
            zf.writestr("traces/events.jsonl", events_jsonl)

        # screenshots/
        screenshot_dir = SCREENSHOTS_DIR / task_id
        if screenshot_dir.is_dir():
            for img in sorted(screenshot_dir.iterdir()):
                if img.is_file():
                    zf.write(img, f"screenshots/{img.name}")

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="debug-{task_id}.zip"',
            "Content-Length": str(buf.getbuffer().nbytes),
        },
    )
