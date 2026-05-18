"""报告序列化。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from argus_py.redaction import (
    redact_finding_entry,
    redact_href,
    redact_log_entry,
    redact_sensitive_text,
    redact_step_params,
)
from argus_py.report.models import Report
from argus_py.utils.jsonx import to_jsonable


def _to_camel(snake: str) -> str:
    """将 snake_case 转换为 camelCase。"""
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _camel_keys(data: Any) -> Any:
    """递归将 dict 的所有 key 从 snake_case 转为 camelCase。"""
    if isinstance(data, dict):
        return {_to_camel(k): _camel_keys(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_camel_keys(item) for item in data]
    return data


def _sanitize_report_path(path: str) -> str:
    """报告对外只保留文件名，避免暴露本机绝对路径。"""
    return Path(path).name


def report_to_dict(report: Report) -> dict[str, Any]:
    """将报告转换为 camelCase dict，所有步骤参数和 URL 中的敏感信息会被脱敏。"""
    # 先以 snake_case 做所有脱敏和结构操作，最后统一转 camelCase
    data = to_jsonable(report)

    # 脱敏 steps 和 task.logs：Report.from_task 让两者指向同一份 task.logs，
    # to_jsonable 序列化后才拆成两个独立 dict 列表，因此必须各自脱敏后写回，
    # 否则 JSON 报告 / 调试包 中的 data["task"]["logs"] 仍是原文。
    steps: list[dict[str, Any]] = [redact_log_entry(s) for s in data.get("steps", [])]
    data["steps"] = steps
    task_dict_for_logs = data.get("task")
    if isinstance(task_dict_for_logs, dict):
        task_dict_for_logs["logs"] = [
            redact_log_entry(s) for s in task_dict_for_logs.get("logs", [])
        ]

    # 脱敏 task 层级的 URL
    task = data.get("task", {})
    start_url = task.get("start_url")
    if isinstance(start_url, str):
        task["start_url"] = redact_href(start_url)
    goal = task.get("goal")
    if isinstance(goal, str):
        task["goal"] = redact_sensitive_text(goal)
    for text_key in ("result_summary", "error_message"):
        value = task.get(text_key)
        if isinstance(value, str):
            task[text_key] = redact_sensitive_text(value)
    report_path = task.get("report_path")
    if isinstance(report_path, str):
        task["report_path"] = _sanitize_report_path(report_path)
    parameters = task.get("parameters")
    if isinstance(parameters, dict):
        task["parameters"] = redact_step_params(parameters)

    # 脱敏 findings
    data["findings"] = [redact_finding_entry(f) for f in data.get("findings", [])]
    task["findings"] = [redact_finding_entry(f) for f in task.get("findings", [])]

    display_steps = [step for step in steps if _should_display_step(step)]
    data["display_steps"] = display_steps
    data["hidden_system_steps"] = [step for step in steps if not _should_display_step(step)]
    data["total_steps_count"] = len(steps)
    data["hidden_steps_count"] = len(steps) - len(display_steps)

    return _camel_keys(data)


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
