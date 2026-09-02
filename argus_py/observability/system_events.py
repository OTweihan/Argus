"""系统事件 JSONL 写入（诊断中心方案第 12 章）。

不建立第二套事件管道：只做有界本地落盘，供诊断查询投影。
路径：``outputs/logs/runtime/system/events.jsonl``。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from argus_py.core.paths import OUTPUT_DIR
from argus_py.observability.context import get_process_run_id
from argus_py.observability.redaction import redact

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_MAX_DETAILS_CHARS = 8 * 1024


def system_events_path(logs_root: Path | None = None) -> Path:
    root = Path(logs_root) if logs_root is not None else OUTPUT_DIR / "logs"
    return root / "runtime" / "system" / "events.jsonl"


def append_system_event(
    event_type: str,
    *,
    result: str = "success",
    source: str = "system",
    details: dict[str, Any] | None = None,
    logs_root: Path | None = None,
) -> None:
    """追加一条系统事件；失败只打 debug，不抛到业务路径。"""
    path = system_events_path(logs_root)
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": "INFO" if result == "success" else "ERROR",
        "service": "argus-system",
        "component": "system",
        "logger": "argus.system",
        "message": event_type,
        "eventType": event_type,
        "eventId": f"evt_{uuid4().hex}",
        "runId": get_process_run_id(),
        "instanceId": os.getenv("ARGUS_INSTANCE_ID") or None,
        "result": result,
        "source": source,
        "pid": os.getpid(),
    }
    if details:
        payload["details"] = redact(details)
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(line) > _MAX_DETAILS_CHARS:
        # 超长时裁 details，保留可检索的骨架字段
        payload.pop("details", None)
        payload["detailsTruncated"] = True
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError:
        logger.debug("写入系统事件失败: %s", event_type, exc_info=True)
