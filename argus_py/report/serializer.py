"""报告序列化。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from argus_py.browser.snapshot import redact_href, redact_sensitive_text, redact_step_params
from argus_py.report.models import Report
from argus_py.utils.jsonx import to_jsonable


def _redact_finding(finding: dict[str, Any]) -> None:
    """脱敏 finding 中的 url 和截图路径字段（原地修改）。"""
    url = finding.get("url")
    if isinstance(url, str):
        finding["url"] = redact_href(url)
    screenshot_path = finding.get("screenshot_path")
    if isinstance(screenshot_path, str):
        finding["screenshot_path"] = Path(screenshot_path).name
    for text_key in ("title", "description", "location"):
        value = finding.get(text_key)
        if isinstance(value, str):
            finding[text_key] = redact_sensitive_text(value)


def _redact_step(step: dict[str, Any]) -> None:
    """对单步日志的 params 和 URL 字段进行脱敏（原地修改）。"""
    params = step.get("params")
    if isinstance(params, dict):
        step["params"] = redact_step_params(params)
    for url_key in ("url_before", "url_after"):
        val = step.get(url_key)
        if isinstance(val, str):
            step[url_key] = redact_href(val)
    screenshot_path = step.get("screenshot_path")
    if isinstance(screenshot_path, str):
        step["screenshot_path"] = Path(screenshot_path).name
    for text_key in ("message", "error"):
        value = step.get(text_key)
        if isinstance(value, str):
            step[text_key] = redact_sensitive_text(value)


def _sanitize_report_path(path: str) -> str:
    """报告对外只保留文件名，避免暴露本机绝对路径。"""
    return Path(path).name


def report_to_dict(report: Report) -> dict[str, Any]:
    """将报告转换为 dict，所有步骤参数和 URL 中的敏感信息会被脱敏。"""
    data = to_jsonable(report)

    # 脱敏 steps 和 task.logs（两者内容重叠但 JSON 中各自独立存在）
    steps = data.get("steps", [])
    task_logs = data.get("task", {}).get("logs", [])
    for step in steps:
        _redact_step(step)
    for log in task_logs:
        _redact_step(log)

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

    # 脱敏 findings 中的 URL
    findings = data.get("findings", [])
    task_findings = task.get("findings", [])
    for finding in findings:
        _redact_finding(finding)
    for finding in task_findings:
        _redact_finding(finding)

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
