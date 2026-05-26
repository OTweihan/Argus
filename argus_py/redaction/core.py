"""脱敏核心函数：URL、敏感文本、步骤参数。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlunparse

from argus_py.redaction.patterns import (
    REDACTED,
    SENSITIVE_VALUE_KEYWORDS,
    _is_sensitive,
    _is_url_param,
)
from argus_py.redaction.patterns import (
    SENSITIVE_NAME_KEYWORDS as _SENSITIVE_NAME_PATTERNS,
)
from argus_py.redaction.patterns import (
    TEXT_PARAM_NAMES as _TEXT_PARAM_NAMES,
)


def _build_sensitive_text_patterns() -> list[tuple[str, str]]:
    """根据权威关键词列表拼装 ``key=value`` / Bearer / JSON 三类脱敏正则。

    关键词来源统一为 ``SENSITIVE_VALUE_KEYWORDS``（在 ``redaction.patterns``
    集中维护），避免之前正则字面量与 ``_SENSITIVE_NAME_PATTERNS`` 双份维护。
    """
    keywords = "|".join(re.escape(kw) for kw in SENSITIVE_VALUE_KEYWORDS)
    json_keywords = "|".join(
        re.escape(kw)
        for kw in SENSITIVE_VALUE_KEYWORDS
        # JSON 字段中 auth / authorization 通常代表认证头部，单独的 "auth":"..."
        # 多用作字面量字段（如登录类型）；保留 authorization、去除裸 auth，避免误伤。
        if kw not in {"auth"}
    )
    return [
        # key=value 形式（query string、fragment、命令行等）
        (rf"(?i)({keywords})\s*=\s*\S+", r"\1=[REDACTED]"),
        # HTTP Authorization / Auth header（保留原 Bearer / Basic 标签）
        (r"(?i)(Authorization|Auth)\s*:\s*(Bearer|Basic)\s+\S+", r"\1: \2 [REDACTED]"),
        # JSON: "token": "..." / "api_key": "..."
        (rf'(?i)"({json_keywords})"\s*:\s*"[^"]*"', r'"\1":"[REDACTED]"'),
    ]


_SENSITIVE_TEXT_PATTERNS: list[tuple[str, str]] = _build_sensitive_text_patterns()


def redact_href(href: str) -> str:
    """对 URL 进行脱敏：去除 query string 和 fragment，仅保留 path。"""
    stripped = href.strip()
    if not stripped or stripped.startswith("#"):
        return href
    try:
        parsed = urlparse(stripped)
        scheme = parsed.scheme.lower()
        if scheme in {"javascript", "data"}:
            return f"{scheme}:{REDACTED}"
        if scheme and scheme not in {"http", "https"}:
            return f"{scheme}:{REDACTED}"
        netloc = parsed.netloc
        if parsed.hostname:
            try:
                port = f":{parsed.port}" if parsed.port is not None else ""
            except ValueError:
                port = ""
            hostname = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            netloc = f"{hostname}{port}"
        cleaned = urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
        return cleaned or href
    except Exception:
        return href


def redact_sensitive_text(text: str) -> str:
    """对文本中可能出现的 token、api_key、密码、认证头等敏感信息进行脱敏。"""
    for pattern, replacement in _SENSITIVE_TEXT_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def _redact_step_list_value(key: str, value: list[Any], selector_sensitive: bool) -> list[Any]:
    """按父级参数名脱敏列表内容。"""
    redacted: list[Any] = []
    key_sensitive = _is_sensitive(key)
    key_is_url = _is_url_param(key)
    key_is_text = key in _TEXT_PARAM_NAMES
    for item in value:
        if isinstance(item, dict):
            redacted.append(redact_step_params(item))
        elif isinstance(item, str) and key_is_url:
            redacted.append(redact_href(item))
        elif isinstance(item, str) and (key_sensitive or (key_is_text and selector_sensitive)):
            redacted.append(REDACTED)
        elif isinstance(item, str):
            redacted.append(redact_sensitive_text(item))
        else:
            redacted.append(item)
    return redacted


def redact_step_params(params: dict[str, Any]) -> dict[str, Any]:
    """对步骤参数中的 URL、文本和敏感字段进行脱敏。

    当 selector 指向敏感字段（密码/token/secret 等）时，直接
    将输入值置为 [REDACTED]，不依赖正则匹配 key=value 模式。
    """
    redacted: dict[str, Any] = {}
    raw_selector = params.get("selector", "")
    selector_sensitive = isinstance(raw_selector, str) and any(
        p in raw_selector.lower() for p in _SENSITIVE_NAME_PATTERNS
    )
    for key, value in params.items():
        key_lower = key.lower()
        if isinstance(value, str) and _is_url_param(key):
            redacted[key] = redact_href(value)
        elif isinstance(value, str):
            if _is_sensitive(key_lower) or (key_lower in _TEXT_PARAM_NAMES and selector_sensitive):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_sensitive_text(value)
        elif isinstance(value, dict):
            redacted[key] = redact_step_params(value)
        elif isinstance(value, list):
            redacted[key] = _redact_step_list_value(key_lower, value, selector_sensitive)
        else:
            redacted[key] = value
    return redacted
