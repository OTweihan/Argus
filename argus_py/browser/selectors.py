"""元素定位策略。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from playwright.async_api import Locator, Page, expect

from argus_py.browser.errors import ElementNotFoundError

SelectorStrategy = Literal[
    "css",
    "text",
    "role",
    "label",
    "placeholder",
    "test_id",
    "xpath",
]


@dataclass(frozen=True)
class SelectorQuery:
    """一次元素定位请求。"""

    value: str
    strategy: SelectorStrategy = "css"
    name: str | None = None
    exact: bool = False

    @classmethod
    def parse(cls, raw: str) -> "SelectorQuery":
        """从简写字符串解析定位策略。"""
        normalized = raw.strip()
        if normalized.startswith("selector="):
            return cls.parse(normalized.removeprefix("selector=").strip())
        if normalized.startswith("selector:"):
            return cls.parse(normalized.removeprefix("selector:").strip())
        if normalized.startswith("css="):
            css_value = normalized.removeprefix("css=").strip()
            return _parse_contains_selector(css_value) or cls(value=css_value, strategy="css")
        if normalized.startswith("css:"):
            css_value = normalized.removeprefix("css:").strip()
            return _parse_contains_selector(css_value) or cls(value=css_value, strategy="css")
        contains_query = _parse_contains_selector(normalized)
        if contains_query is not None:
            return contains_query
        if normalized.startswith("text="):
            return cls(value=normalized.removeprefix("text="), strategy="text")
        if normalized.startswith("role="):
            role_part = normalized.removeprefix("role=")
            if "[name=" in role_part and role_part.endswith("]"):
                role_name, name_part = role_part.split("[name=", 1)
                return cls(value=role_name, strategy="role", name=name_part[:-1].strip('"'))
            return cls(value=role_part, strategy="role")
        if normalized.startswith("label="):
            return cls(value=normalized.removeprefix("label="), strategy="label")
        if normalized.startswith("placeholder="):
            return cls(value=normalized.removeprefix("placeholder="), strategy="placeholder")
        if normalized.startswith("testid="):
            return cls(value=normalized.removeprefix("testid="), strategy="test_id")
        if normalized.startswith("xpath="):
            return cls(value=normalized.removeprefix("xpath="), strategy="xpath")
        return cls(value=normalized, strategy="css")


def _parse_contains_selector(raw: str) -> SelectorQuery | None:
    """兼容 LLM 常生成的 jQuery 风格 :contains() 选择器。"""
    match = re.fullmatch(
        r"(?P<tag>[a-zA-Z][\w-]*)\:contains\((?P<quote>['\"])(?P<text>.*?)(?P=quote)\)",
        raw.strip(),
    )
    if match is None:
        return None

    tag = match.group("tag").lower()
    value = match.group("text").strip()
    if tag == "button":
        return SelectorQuery(value="button", strategy="role", name=value)
    if tag == "a":
        return SelectorQuery(value="link", strategy="role", name=value)
    return SelectorQuery(value=value, strategy="text")


def css(selector: str) -> SelectorQuery:
    """CSS 定位。"""
    return SelectorQuery(value=selector, strategy="css")


def text(value: str, exact: bool = False) -> SelectorQuery:
    """文本定位。"""
    return SelectorQuery(value=value, strategy="text", exact=exact)


def role(role_name: str, name: str | None = None, exact: bool = False) -> SelectorQuery:
    """ARIA role 定位。"""
    return SelectorQuery(value=role_name, strategy="role", name=name, exact=exact)


def label(value: str, exact: bool = False) -> SelectorQuery:
    """Label 定位。"""
    return SelectorQuery(value=value, strategy="label", exact=exact)


def placeholder(value: str, exact: bool = False) -> SelectorQuery:
    """Placeholder 定位。"""
    return SelectorQuery(value=value, strategy="placeholder", exact=exact)


def test_id(value: str) -> SelectorQuery:
    """data-testid 定位。"""
    return SelectorQuery(value=value, strategy="test_id")


def xpath(expression: str) -> SelectorQuery:
    """XPath 定位。"""
    return SelectorQuery(value=expression, strategy="xpath")


def resolve_locator(page: Page, query: str | SelectorQuery) -> Locator:
    """将定位请求转换为 Playwright Locator。"""
    parsed = SelectorQuery.parse(query) if isinstance(query, str) else query
    if parsed.strategy == "css":
        return page.locator(parsed.value).first
    if parsed.strategy == "text":
        return page.get_by_text(parsed.value, exact=parsed.exact).first
    if parsed.strategy == "role":
        options = {"exact": parsed.exact}
        if parsed.name is not None:
            options["name"] = parsed.name
        return page.get_by_role(parsed.value, **options).first
    if parsed.strategy == "label":
        return page.get_by_label(parsed.value, exact=parsed.exact).first
    if parsed.strategy == "placeholder":
        return page.get_by_placeholder(parsed.value, exact=parsed.exact).first
    if parsed.strategy == "test_id":
        return page.get_by_test_id(parsed.value).first
    if parsed.strategy == "xpath":
        return page.locator(f"xpath={parsed.value}").first
    raise ValueError(f"不支持的定位策略：{parsed.strategy}")


async def require_visible(
    page: Page,
    query: str | SelectorQuery,
    timeout_ms: int = 10000,
) -> Locator:
    """定位并等待元素可见。"""
    locator = resolve_locator(page, query)
    parsed = SelectorQuery.parse(query) if isinstance(query, str) else query
    try:
        await expect(locator).to_be_visible(timeout=timeout_ms)
    except Exception as exc:
        raise ElementNotFoundError(parsed.value, parsed.strategy) from exc
    return locator
