"""任务报告路由。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from argus_py.api.dependencies import get_task_service
from argus_py.core.paths import REPORTS_DIR
from argus_py.task.models import Task
from argus_py.task.service import TaskService

router = APIRouter(prefix="/tasks", tags=["reports"])


@router.get("/{task_id}/report")
async def get_task_report(
    task_id: str,
    format: str = Query(default="html", pattern="^(html|json)$"),
    service: TaskService = Depends(get_task_service),
) -> FileResponse:
    """返回任务报告文件，默认 HTML，可通过 format=json 获取结构化报告。"""
    task = service.get_task(task_id)
    if format == "json":
        return _json_report_response(task)
    return _html_report_response(task)


@router.get("/{task_id}/report.json")
async def get_task_report_json(
    task_id: str,
    service: TaskService = Depends(get_task_service),
) -> FileResponse:
    """返回任务 JSON 报告文件。"""
    return _json_report_response(service.get_task(task_id))


def _html_report_response(task: Task) -> FileResponse:
    """返回 HTML 报告。"""
    html_path = _resolve_html_report_path(task)
    return FileResponse(html_path, media_type="text/html")


def _json_report_response(task: Task) -> FileResponse:
    """返回 JSON 报告。"""
    html_path = _resolve_html_report_path(task)
    json_path = html_path.parent / "report.json"
    if not json_path.exists():
        raise _report_not_found(task.task_id, "JSON 报告文件不存在。")
    return FileResponse(json_path, media_type="application/json", filename="report.json")


def _resolve_html_report_path(task: Task) -> Path:
    """解析并校验 HTML 报告路径。"""
    if not task.report_path:
        raise _report_not_found(task.task_id, "任务尚未生成报告。")
    report_path = Path(task.report_path).expanduser().resolve()
    reports_dir = REPORTS_DIR.resolve()
    if not report_path.is_relative_to(reports_dir):
        raise _report_not_found(task.task_id, "报告路径不在允许的报告目录下。")
    if not report_path.exists():
        raise _report_not_found(task.task_id, "HTML 报告文件不存在。")
    return report_path


def _report_not_found(task_id: str, message: str) -> HTTPException:
    """生成报告不存在错误。"""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "REPORT_NOT_FOUND",
            "message": message,
            "details": {"taskId": task_id},
        },
    )
