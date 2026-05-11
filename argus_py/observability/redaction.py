"""日志脱敏工具。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}
MASK = "***"


def redact(value: Any) -> Any:
    """递归脱敏可 JSON 序列化的数据。"""
    if isinstance(value, Mapping):
        return {
            str(key): MASK if _is_sensitive_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, str):
        return redact_url(value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [redact(item) for item in value]
    return value


def redact_url(value: str) -> str:
    """脱敏 URL query 中的敏感字段。"""
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.scheme or not parts.netloc or not parts.query:
        return value
    query = [
        (key, MASK if _is_sensitive_key(key) else item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEYS)
