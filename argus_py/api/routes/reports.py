"""任务报告路由 — 只做 IO 适配，路径解析委托 TaskService。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import FileResponse

from argus_py.api.dependencies import get_task_query_service
from argus_py.api.params import TaskIdPath
from argus_py.core.exceptions import TaskError
from argus_py.task.query import TaskQueryService

router = APIRouter(prefix="/tasks", tags=["reports"])


@router.get("/{task_id}/report")
def get_task_report(
    task_id: TaskIdPath,
    format: str = Query(default="html", pattern="^(html|json)$"),
    download: bool = Query(default=False),
    query: TaskQueryService = Depends(get_task_query_service),
) -> FileResponse:
    """返回任务报告文件，默认 HTML，可通过 format=json 获取结构化报告。"""
    task = query.get_task(task_id)
    try:
        report_path = query.resolve_report_path(task)
    except TaskError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REPORT_NOT_FOUND", "message": str(e), "details": {"taskId": task_id}},
        )

    if format == "json":
        json_path = report_path.parent / "report.json"
        if not json_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "REPORT_NOT_FOUND",
                    "message": "JSON 报告文件不存在。",
                    "details": {"taskId": task_id},
                },
            )
        if download:
            return FileResponse(json_path, media_type="application/json", filename="report.json")
        return FileResponse(json_path, media_type="application/json")

    if download:
        return FileResponse(report_path, media_type="text/html", filename="index.html")
    return FileResponse(report_path, media_type="text/html")


@router.get("/{task_id}/report.json")
def get_task_report_json(
    task_id: TaskIdPath,
    download: bool = Query(default=False),
    query: TaskQueryService = Depends(get_task_query_service),
) -> FileResponse:
    """返回任务 JSON 报告文件。"""
    task = query.get_task(task_id)
    try:
        report_path = query.resolve_report_path(task)
    except TaskError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REPORT_NOT_FOUND", "message": str(e), "details": {"taskId": task_id}},
        )
    json_path = report_path.parent / "report.json"
    if not json_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "REPORT_NOT_FOUND",
                "message": "JSON 报告文件不存在。",
                "details": {"taskId": task_id},
            },
        )
    if download:
        return FileResponse(json_path, media_type="application/json", filename="report.json")
    return FileResponse(json_path, media_type="application/json")


@router.get("/{task_id}/screenshots/{filename:path}")
def get_task_screenshot(
    task_id: TaskIdPath,
    filename: str = Path(pattern=r"^[a-zA-Z0-9_.-]+$"),
    query: TaskQueryService = Depends(get_task_query_service),
) -> FileResponse:
    """返回任务截图文件。"""
    query.get_task(task_id)
    try:
        screenshot_path = query.resolve_screenshot_path(task_id, filename)
    except TaskError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return FileResponse(screenshot_path)
