"""报告序列化。"""

from __future__ import annotations

from typing import Any

from argus_py.report.models import Report
from argus_py.utils.jsonx import to_jsonable


def report_to_dict(report: Report) -> dict[str, Any]:
    """将报告转换为 dict。"""
    return to_jsonable(report)
