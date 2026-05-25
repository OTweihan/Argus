"""Playwright 页面 DOM 评估：交互元素、HTML 摘要、可访问性树。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from playwright.async_api import Page

from argus_py.browser.snapshot.html_pipeline import clean_html_for_prompt
from argus_py.browser.snapshot.meta import ConsoleMessage, InteractiveElement, PageSnapshot

_JS_DIR = Path(__file__).parent
_JS_CODE = (_JS_DIR / "snapshot_dom.js").read_text("utf-8")

logger = logging.getLogger(__name__)

# 从 JS 文件中按标记提取对应的函数表达式
_JS_RE = re.compile(r"// @@(\w+)@@\n(.*?)(?=\n// @@|\Z)", re.DOTALL)
_JS_FUNCS: dict[str, str] = {}
for m in _JS_RE.finditer(_JS_CODE):
    _JS_FUNCS[m.group(1)] = m.group(2).strip()


def _load_js(name: str) -> str:
    """加载 snapshot_dom.js 中标记为 ``name`` 的函数表达式。"""
    return _JS_FUNCS[name]


async def capture_snapshot(
    page: Page,
    max_text_length: int = 4000,
    max_elements: int = 80,
    console_messages: list[ConsoleMessage] | None = None,
) -> PageSnapshot:
    """提取页面标题、URL、正文、可交互元素摘要、HTML 摘要、可访问性树和控制台错误。"""
    title = await page.title()
    body = page.locator("body")
    text = ""
    if await body.count() > 0:
        text = (await body.inner_text(timeout=3000))[:max_text_length]

    current_url = page.url

    raw_elements = await page.locator("a,button,input,textarea,select,[role],summary").evaluate_all(
        _load_js("evaluateElements"),
        max_elements,
    )
    elements = [InteractiveElement(**item) for item in raw_elements]

    html_summary = await _capture_html_summary(page)
    accessibility_tree = await _capture_accessibility_summary(page)

    all_messages = console_messages or []
    errors = [
        msg
        for msg in all_messages
        if msg.level in {"error", "warning"} and msg.page_url == current_url
    ]

    return PageSnapshot(
        url=current_url,
        title=title,
        text=text,
        interactive_elements=elements,
        console_messages=all_messages,
        console_errors=errors,
        html_summary=html_summary,
        accessibility_tree=accessibility_tree,
        metadata={"element_count": len(elements)},
    )


async def _capture_html_summary(page: Page, max_length: int = 6000) -> str:
    """获取页面 body 的清洗后 HTML 摘要。"""
    try:
        body = page.locator("body")
        if await body.count() == 0:
            return ""
        html = await body.evaluate("el => el.outerHTML")
        cleaned = clean_html_for_prompt(html)
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length] + "\n... [truncated]"
        return cleaned
    except Exception:
        logger.exception("获取 DOM 评估失败")
        return ""


async def _capture_accessibility_summary(page: Page, max_nodes: int = 80) -> str:
    """基于 DOM 属性生成轻量可访问性摘要，不依赖 Playwright accessibility API。"""
    try:
        raw = await page.evaluate(
            _load_js("buildAccessibilityTree"),
            max_nodes,
        )
        return raw or ""
    except Exception:
        logger.exception("获取 DOM 评估失败")
        return ""
