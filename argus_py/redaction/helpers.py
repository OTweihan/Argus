"""统一的对日志和问题记录的脱敏辅助函数，收敛三处重复的脱敏编排。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from argus_py.redaction.core import redact_href, redact_sensitive_text, redact_step_params


def _strip_path(path: str | None) -> str | None:
    if path:
        return Path(path).name
    return None


def redact_log_entry(data: dict[str, Any]) -> dict[str, Any]:
    """脱敏日志条目字典（操作副本并返回）。"""
    result = dict(data)
    params = result.get("params")
    if isinstance(params, dict):
        result["params"] = redact_step_params(params)
    for url_key in ("urlBefore", "urlAfter"):
        value = result.get(url_key)
        if isinstance(value, str):
            result[url_key] = redact_href(value)
    if "screenshotPath" in result:
        result["screenshotPath"] = _strip_path(result["screenshotPath"])
    for text_key in ("message", "error"):
        value = result.get(text_key)
        if isinstance(value, str):
            result[text_key] = redact_sensitive_text(value)
    return result


def redact_finding_entry(data: dict[str, Any]) -> dict[str, Any]:
    """脱敏问题记录条目字典（操作副本并返回）。"""
    result = dict(data)
    url = result.get("url")
    if isinstance(url, str):
        result["url"] = redact_href(url)
    if "screenshotPath" in result:
        result["screenshotPath"] = _strip_path(result["screenshotPath"])
    for text_key in ("title", "description", "location"):
        value = result.get(text_key)
        if isinstance(value, str):
            result[text_key] = redact_sensitive_text(value)
    return result
