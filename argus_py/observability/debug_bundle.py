"""任务调试包构建。"""

from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from argus_py.core.exceptions import TaskError
from argus_py.core.paths import OUTPUT_DIR, SCREENSHOTS_DIR
from argus_py.infra.temp_cleanup import DEBUG_BUNDLE_TMP_PREFIX
from argus_py.task.models import Task

logger = logging.getLogger(__name__)

# 调试包大小上限：100 MB（近似，按源文件未压缩大小计算）
_BUNDLE_MAX_SIZE_BYTES = 100 * 1024 * 1024


class DebugBundleBuilder:
    """构建任务调试包 zip 文件。

    将 task.json、LLM trace、时间线事件、截图打包为单个 zip，
    供下载用于离线调试。
    """

    def build(self, task_id: str, task: Task, events: list[dict[str, Any]] | None = None) -> str:
        """构建调试包 zip，返回临时文件路径。

        ``events`` 可选传入时间线事件列表；调用方可从 ``TaskTimelineService``
        或兼容接口获取。打包 task.json + trace + 事件 + 截图；大小超过
        ``_BUNDLE_MAX_SIZE_BYTES`` 时跳过后续文件并记录警告。
        """
        tmp = tempfile.NamedTemporaryFile(
            delete=False, prefix=DEBUG_BUNDLE_TMP_PREFIX, suffix=".zip"
        )
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
                trace_path = self._resolve_trace_path(task_id)
                if trace_path.exists() and _check_size(trace_path.stat().st_size):
                    zf.write(trace_path, "traces/llm.jsonl")

                # traces/events.jsonl
                if events:
                    events_bytes = "\n".join(
                        json.dumps(e, ensure_ascii=False) for e in events
                    ).encode()
                    if _check_size(len(events_bytes)):
                        zf.writestr("traces/events.jsonl", events_bytes)

                # screenshots/
                raw_screenshot_dir = (SCREENSHOTS_DIR / task_id).resolve()
                if (
                    raw_screenshot_dir.is_relative_to(SCREENSHOTS_DIR.resolve())
                    and raw_screenshot_dir.is_dir()
                ):
                    for img in sorted(raw_screenshot_dir.iterdir()):
                        if not img.is_file():
                            continue
                        if not _check_size(img.stat().st_size):
                            break
                        zf.write(img, f"screenshots/{img.name}")
        finally:
            tmp.close()

        if skipped:
            logger.warning(
                "调试包超出大小上限 (%d MB)，部分文件已跳过：task_id=%s",
                _BUNDLE_MAX_SIZE_BYTES // (1024 * 1024),
                task_id,
            )

        return tmp_path

    @staticmethod
    def _resolve_trace_path(task_id: str) -> Path:
        """解析并校验 trace 文件路径，防止目录穿越。"""
        raw = (OUTPUT_DIR / "traces" / f"{task_id}.jsonl").resolve()
        if not raw.is_relative_to(OUTPUT_DIR.resolve()):
            raise TaskError("trace 路径不在允许的输出目录下。")
        return raw
