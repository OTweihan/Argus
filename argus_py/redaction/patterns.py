"""敏感字段模式与判断谓词。

集中管理整个项目脱敏逻辑使用的关键词与字段名集合，便于审计 / 增删：

- ``SENSITIVE_NAME_KEYWORDS``：字段名（substring）匹配关键词，参与
  ``_is_sensitive(name)`` 判断，影响 ``redact_step_params`` 等结构化脱敏。
- ``SENSITIVE_VALUE_KEYWORDS``：``key=value`` / JSON 文本正则脱敏关键词，
  在 ``redaction.core`` 中动态拼接到 ``_SENSITIVE_TEXT_PATTERNS``。
- ``URL_PARAM_NAMES`` / ``TEXT_PARAM_NAMES``：步骤参数 URL / 文本字段名集合。
- ``REDACTED``：统一替换占位符。
"""

# 字段名（substring）匹配 —— 用于 `_is_sensitive(name)`。
# 加入新关键词时尽量保留 ASCII 小写，并避免太短/通用的 substring（如 "auth"
# 会误命中 "author"），以减少误伤；广义的关键词放到 SENSITIVE_VALUE_KEYWORDS。
SENSITIVE_NAME_KEYWORDS: tuple[str, ...] = (
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

# `key=value` / `"key":"value"` 正则关键词 —— 由 `redaction.core` 拼成正则，
# 只在“整词”位置匹配（key 后跟 `=` / `: "..."`），不会误伤普通文本。
SENSITIVE_VALUE_KEYWORDS: tuple[str, ...] = (
    "token",
    "access_token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "credential",
    "auth",
    "authorization",
    "session",
    "sess",
    "sid",
    "jwt",
)

URL_PARAM_NAMES: frozenset[str] = frozenset(
    {"url", "href", "start_url", "current_url", "url_before", "url_after"}
)
TEXT_PARAM_NAMES: frozenset[str] = frozenset({"text", "value", "input", "content"})
REDACTED: str = "[REDACTED]"

# ── 向后兼容的私有别名 ────────────────────────────────────────────
# 项目内仍有模块直接 `from argus_py.redaction.patterns import _SENSITIVE_NAME_PATTERNS`
# 等私有名字。保留这些别名指向新公开常量，避免一次性扩散修改。
_SENSITIVE_NAME_PATTERNS = SENSITIVE_NAME_KEYWORDS
_URL_PARAM_NAMES = URL_PARAM_NAMES
_TEXT_PARAM_NAMES = TEXT_PARAM_NAMES
_REDACTED = REDACTED


def _is_sensitive(name: str | None) -> bool:
    """检查 name/type 是否匹配敏感字段模式。"""
    if not name:
        return False
    lower = name.lower()
    return any(keyword in lower for keyword in SENSITIVE_NAME_KEYWORDS)


def _is_url_param(name: str) -> bool:
    lower = name.lower()
    return (
        lower in URL_PARAM_NAMES
        or lower.endswith("_url")
        or lower.endswith("_href")
        or lower.endswith("url")
        or lower.endswith("href")
    )
