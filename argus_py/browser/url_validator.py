"""URL 校验工具。"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_HAS_WHITESPACE_OR_CJK = re.compile(r"[\s\u4e00-\u9fff]")
_HAS_CTRL_OR_SPACE = re.compile(r"[\x00-\x20\x7f]")


class UrlValidationCode(str):
    """URL 校验结果码。"""

    VALID = "valid"
    EMPTY_URL = "empty_url"
    INVALID_SCHEME = "invalid_scheme"
    MALFORMED_URL = "malformed_url"
    MARKDOWN_LINK_TEXT = "markdown_link_text"
    PLAIN_TEXT = "plain_text"


class UrlValidationResult:
    """URL 校验结果。"""

    __slots__ = ("code", "url", "error_message")

    def __init__(
        self,
        code: str,
        url: str,
        error_message: str = "",
    ) -> None:
        self.code = code
        self.url = url
        self.error_message = error_message

    def is_ok(self) -> bool:
        """校验是否通过。"""
        return self.code == UrlValidationCode.VALID

    def __repr__(self) -> str:
        return f"UrlValidationResult(code={self.code}, url={self.url!r})"


def validate_url(
    url: str | None,
    current_page_url: str | None = None,
) -> UrlValidationResult:
    """校验 URL 合法性，只允许标准 http/https 绝对 URL。

    校验规则：
    1. 空/None → EMPTY_URL
    2. Markdown 链接文本 → MARKDOWN_LINK_TEXT
    3. 含空格/中文且无 scheme → PLAIN_TEXT
    4. 无 scheme → MALFORMED_URL
    5. scheme 不是 http/https → INVALID_SCHEME
    6. 无 netloc → MALFORMED_URL
    7. 其余视为 VALID
    """
    if not url or not url.strip():
        return UrlValidationResult(
            code=UrlValidationCode.EMPTY_URL,
            url=url or "",
            error_message="URL 为空。",
        )

    stripped = url.strip()

    if _MARKDOWN_LINK_RE.search(stripped):
        return UrlValidationResult(
            code=UrlValidationCode.MARKDOWN_LINK_TEXT,
            url=stripped,
            error_message="goto.url 不支持 Markdown 链接文本，必须直接提供 http/https 绝对 URL。",
        )

    parsed = urlparse(stripped)

    # 无 scheme → 非标准绝对 URL
    if not parsed.scheme:
        if _HAS_WHITESPACE_OR_CJK.search(stripped):
            return UrlValidationResult(
                code=UrlValidationCode.PLAIN_TEXT,
                url=stripped,
                error_message=f"输入不是合法 URL：{stripped[:100]}",
            )
        return UrlValidationResult(
            code=UrlValidationCode.MALFORMED_URL,
            url=stripped,
            error_message=f"goto.url 必须是 http/https 绝对 URL：{stripped[:100]}",
        )

    # 有 scheme 但 URL 中包含不允许的空白或控制字符
    if _HAS_CTRL_OR_SPACE.search(stripped):
        return UrlValidationResult(
            code=UrlValidationCode.MALFORMED_URL,
            url=stripped,
            error_message=f"URL 包含不允许的空格或控制字符：{stripped[:100]}",
        )

    # scheme 校验
    if parsed.scheme not in ("http", "https"):
        return UrlValidationResult(
            code=UrlValidationCode.INVALID_SCHEME,
            url=stripped,
            error_message=f"不支持的 URL scheme：{parsed.scheme}",
        )

    # 必须有 netloc
    if not parsed.netloc:
        return UrlValidationResult(
            code=UrlValidationCode.MALFORMED_URL,
            url=stripped,
            error_message=f"URL 格式不合法，缺少主机名：{stripped[:100]}",
        )

    return UrlValidationResult(
        code=UrlValidationCode.VALID,
        url=stripped,
    )
