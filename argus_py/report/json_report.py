"""JSON 报告导出。"""

from __future__ import annotations

from pathlib import Path

from argus_py.report.models import Report
from argus_py.report.serializer import report_to_dict
from argus_py.utils.jsonx import write_json


def write_json_report(report: Report, path: str | Path) -> Path:
    """写入 JSON 报告。"""
    return write_json(path, report_to_dict(report))
