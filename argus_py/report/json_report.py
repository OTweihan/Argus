"""JSON 报告导出。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from argus_py.utils.jsonx import write_json


def write_json_report(report_dict: dict[str, Any], path: str | Path) -> Path:
    """写入 JSON 报告。"""
    return write_json(path, report_dict)
