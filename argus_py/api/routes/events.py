"""任务时间线与 LLM 追踪 API 路由。"""

from __future__ import annotations

import itertools
import json
import logging
import os
import tempfile
import zipfile
from collections.abc import Iterable, Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from argus_py.api.dependencies import get_task_service
from argus_py.api.schemas.llm_trace import LLMTraceResponse
from argus_py.core.exceptions import TaskError
from argus_py.core.paths import OUTPUT_DIR, SCREENSHOTS_DIR
from argus_py.infra.temp_cleanup import DEBUG_BUNDLE_TMP_PREFIX
from argus_py.task.service import TaskService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["events"])

# 调试包大小上限：100 MB（近似，按源文件未压缩大小计算）
_BUNDLE_MAX_SIZE_BYTES = 100 * 1024 * 1024


def _iter_filtered_trace_records(
    lines: Iterable[str],
    trace_id_filter: str | None,
) -> Iterator[dict[str, Any]]:
    """流式解析 JSONL 行，按 trace_id 过滤并跳过空 / 损坏行。

    由调用方负责文件句柄生命周期（必须在 ``with open`` 块内消化迭代器，
    否则文件会被关闭）。损坏的 JSON 行只警告并跳过，不抛 500。
    """
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("跳过 JSONL 中的非法行：%s", line[:120])
            continue
        if trace_id_filter and record.get("trace_id") != trace_id_filter:
            continue
        yield record


def _serialize_trace(record: dict[str, Any]) -> dict[str, Any]:
    """将原始 trace 记录通过 LLMTraceResponse 校验后转回 JSON 友好字典。"""
    return LLMTraceResponse.model_validate(record).model_dump(by_alias=True, mode="json")


@router.get("/{task_id}/events")
def list_task_events(
    task_id: str,
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
    task_id: str,
    skip: int = 0,
    limit: int = 50,
    trace_id: str | None = None,
    service: TaskService = Depends(get_task_service),
):
    """返回任务的 LLM 调用追踪记录（从 JSONL 文件读取）。

    支持分页（skip/limit）和按 trace_id 过滤；同步文件 IO 在线程池执行。
    采用 ``itertools.islice`` 流式分页：仅对落入 [skip, skip+limit) 窗口的
    记录做 Pydantic 验证 + dump，避免大 trace 文件全量解析。
    """
    try:
        service.get_task(task_id)
    except TaskError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    trace_path = OUTPUT_DIR / "traces" / f"{task_id}.jsonl"
    if not trace_path.exists():
        return []

    skip = max(skip, 0)
    stop: int | None = (skip + limit) if limit > 0 else None
    with open(trace_path, encoding="utf-8") as f:
        sliced = itertools.islice(_iter_filtered_trace_records(f, trace_id), skip, stop)
        return [_serialize_trace(record) for record in sliced]


@router.get("/{task_id}/llm-traces/{trace_id}")
def get_trace_detail(
    task_id: str,
    trace_id: str,
    service: TaskService = Depends(get_task_service),
):
    """返回单条 LLM 调用的完整追踪记录（同步文件 IO，线程池执行）。

    复用 ``_iter_filtered_trace_records`` 流式扫描，命中即早退。
    """
    try:
        service.get_task(task_id)
    except TaskError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    trace_path = OUTPUT_DIR / "traces" / f"{task_id}.jsonl"
    if not trace_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="追踪记录不存在")
    with open(trace_path, encoding="utf-8") as f:
        record = next(_iter_filtered_trace_records(f, trace_id), None)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="追踪记录不存在")
    return _serialize_trace(record)


@router.get("/{task_id}/debug-bundle")
def download_debug_bundle(
    task_id: str,
    service: TaskService = Depends(get_task_service),
):
    """下载任务调试包（task.json + traces + 事件 + 截图）。

    使用临时文件构建，避免大截图撑爆内存；超过 _BUNDLE_MAX_SIZE_BYTES 时
    跳过后续文件并记录警告。同步 IO 在线程池执行，避免阻塞事件循环。
    """
    try:
        task = service.get_task(task_id)
    except TaskError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    # 加专属前缀，便于服务启动时的残留清理扫描识别（参见 infra/temp_cleanup.py）。
    tmp = tempfile.NamedTemporaryFile(delete=False, prefix=DEBUG_BUNDLE_TMP_PREFIX, suffix=".zip")
    tmp_path = tmp.name
    total_size = 0
    skipped = False

    def _check_size(added: int) -> bool:
        nonlocal total_size, skipped
        if total_size + added > _BUNDLE_MAX_SIZE_BYTES:
            skipped = True
            return False
        total_size += added
        return True

    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            # task.json
            from argus_py.utils.jsonx import to_jsonable

            task_bytes = json.dumps(to_jsonable(task), ensure_ascii=False, indent=2).encode()
            if _check_size(len(task_bytes)):
                zf.writestr("task.json", task_bytes)

            # traces/llm.jsonl
            trace_path = OUTPUT_DIR / "traces" / f"{task_id}.jsonl"
            if trace_path.exists() and _check_size(trace_path.stat().st_size):
                zf.write(trace_path, "traces/llm.jsonl")

            # traces/events.jsonl
            events = service.list_timeline_events(task_id)
            if events:
                events_bytes = "\n".join(json.dumps(e, ensure_ascii=False) for e in events).encode()
                if _check_size(len(events_bytes)):
                    zf.writestr("traces/events.jsonl", events_bytes)

            # screenshots/
            screenshot_dir = SCREENSHOTS_DIR / task_id
            if screenshot_dir.is_dir():
                for img in sorted(screenshot_dir.iterdir()):
                    if not img.is_file():
                        continue
                    if not _check_size(img.stat().st_size):
                        break  # 超限后不再继续加截图
                    zf.write(img, f"screenshots/{img.name}")
    finally:
        tmp.close()

    if skipped:
        logger.warning(
            "调试包超出大小上限 (%d MB)，部分文件已跳过：task_id=%s",
            _BUNDLE_MAX_SIZE_BYTES // (1024 * 1024),
            task_id,
        )

    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=f"debug-{task_id}.zip",
        headers={
            "Content-Disposition": f'attachment; filename="debug-{task_id}.zip"',
        },
        background=BackgroundTask(os.unlink, tmp_path),
    )
