"""敏感字段模式与判断谓词。"""

_SENSITIVE_NAME_PATTERNS = (
    "password",
    "passwd",
    "passcode",
    "pwd",
    "token",
    "apikey",
    "api_key",
    "secret",
    "credential",
    "session",
    "jwt",
    "authorization",
)
_URL_PARAM_NAMES = {"url", "href", "start_url", "current_url", "url_before", "url_after"}
_TEXT_PARAM_NAMES = {"text", "value", "input", "content"}
_REDACTED = "[REDACTED]"


def _is_sensitive(name: str | None) -> bool:
    """检查 name/type 是否匹配敏感字段模式。"""
    if not name:
        return False
    lower = name.lower()
    return any(pattern in lower for pattern in _SENSITIVE_NAME_PATTERNS)


def _is_url_param(name: str) -> bool:
    lower = name.lower()
    return (
        lower in _URL_PARAM_NAMES
        or lower.endswith("_url")
        or lower.endswith("_href")
        or lower.endswith("url")
        or lower.endswith("href")
    )
