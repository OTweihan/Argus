"""前端异常事件 JSONL 写入（诊断中心方案 17.8）。"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from argus_py.core.paths import OUTPUT_DIR
from argus_py.observability.context import get_process_run_id, new_request_id
from argus_py.observability.redaction import redact

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_MAX_MESSAGE_CHARS = 4 * 1024
_MAX_STACK_CHARS = 16 * 1024
_MAX_LINE_CHARS = 24 * 1024


def frontend_events_path(logs_root: Path | None = None) -> Path:
    root = Path(logs_root) if logs_root is not None else OUTPUT_DIR / "logs"
    return root / "runtime" / "web" / "frontend-events.jsonl"


def append_frontend_event(
    payload: dict[str, Any],
    *,
    logs_root: Path | None = None,
) -> dict[str, Any]:
    """校验并追加一条前端异常事件，返回落盘后的规范化字典。"""
    message = str(payload.get("message") or "").strip() or "(empty)"
    level = str(payload.get("level") or "ERROR").upper()
    if level not in {"DEBUG", "INFO", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL"}:
        level = "ERROR"
    if level == "WARNING":
        level = "WARN"

    timestamp = str(payload.get("timestamp") or "").strip()
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()

    request_id = payload.get("requestId") or payload.get("request_id")
    request_id_text = str(request_id).strip() if request_id else ""
    if not request_id_text:
        request_id_text = new_request_id()

    record: dict[str, Any] = {
        "timestamp": timestamp,
        "level": level,
        "service": "argus-web",
        "component": "web",
        "logger": str(payload.get("module") or "frontend").strip() or "frontend",
        "message": message[:_MAX_MESSAGE_CHARS],
        "requestId": request_id_text,
        "runId": get_process_run_id(),
        "eventId": f"fe_{uuid4().hex}",
    }
    error_type = payload.get("errorType") or payload.get("error_type")
    if error_type:
        record["errorType"] = str(error_type)[:256]
    stack = payload.get("errorStack") or payload.get("error_stack") or payload.get("stack")
    if stack:
        record["errorStack"] = str(stack)[:_MAX_STACK_CHARS]
        record["exception"] = record["errorStack"]
    for key in ("url", "userAgent", "page"):
        value = payload.get(key)
        if value:
            record[key] = str(value)[:1024]

    record = redact(record)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(line) > _MAX_LINE_CHARS:
        record.pop("errorStack", None)
        record.pop("exception", None)
        record["detailsTruncated"] = True
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)

    path = frontend_events_path(logs_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return record
