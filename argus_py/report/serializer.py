"""报告序列化。"""

from __future__ import annotations

from typing import Any

from argus_py.report.models import Report
from argus_py.utils.jsonx import to_jsonable


def report_to_dict(report: Report) -> dict[str, Any]:
    """将报告转换为 dict。"""
    data = to_jsonable(report)
    steps = data.get("steps", [])
    display_steps = [step for step in steps if _should_display_step(step)]
    data["display_steps"] = display_steps
    data["total_steps_count"] = len(steps)
    data["hidden_steps_count"] = len(steps) - len(display_steps)
    return data


def _should_display_step(step: dict[str, Any]) -> bool:
    """判断步骤是否应该展示在 HTML 报告主时间线中。"""
    if step.get("result") != "success":
        return True

    action = step.get("action")
    if action == "wait":
        return False
    if action == "screenshot":
        return False
    return True
