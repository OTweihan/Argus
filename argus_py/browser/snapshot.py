"""页面结构化快照。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page


@dataclass
class InteractiveElement:
    """页面可交互元素摘要。"""

    index: int
    tag: str
    text: str = ""
    role: str | None = None
    element_type: str | None = None
    name: str | None = None
    element_id: str | None = None
    placeholder: str | None = None
    aria_label: str | None = None
    href: str | None = None
    visible: bool = True


@dataclass
class ConsoleMessage:
    """浏览器控制台消息。"""

    level: str
    text: str


@dataclass
class PageSnapshot:
    """页面观察结果。"""

    url: str
    title: str
    text: str
    interactive_elements: list[InteractiveElement] = field(default_factory=list)
    console_messages: list[ConsoleMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_prompt_text(self, max_elements: int = 40) -> str:
        """转换为适合传给 LLM 的紧凑文本。"""
        lines = [f"URL: {self.url}", f"Title: {self.title}", "Interactive elements:"]
        for item in self.interactive_elements[:max_elements]:
            label = item.text or item.aria_label or item.placeholder or item.name or item.element_id or ""
            lines.append(f"- [{item.index}] <{item.tag}> {label}".strip())
        lines.append("Page text:")
        lines.append(self.text)
        return "\n".join(lines)


async def capture_snapshot(
    page: Page,
    max_text_length: int = 4000,
    max_elements: int = 80,
    console_messages: list[ConsoleMessage] | None = None,
) -> PageSnapshot:
    """提取页面标题、URL、正文和可交互元素摘要。"""
    title = await page.title()
    body = page.locator("body")
    text = ""
    if await body.count() > 0:
        text = (await body.inner_text(timeout=3000))[:max_text_length]

    raw_elements = await page.locator("a,button,input,textarea,select,[role],summary").evaluate_all(
        """
        (els, maxElements) => els.slice(0, maxElements).map((el, index) => {
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return {
            index,
            tag: el.tagName.toLowerCase(),
            text: (el.innerText || el.value || '').trim().slice(0, 160),
            role: el.getAttribute('role'),
            element_type: el.getAttribute('type'),
            name: el.getAttribute('name'),
            element_id: el.id || null,
            placeholder: el.getAttribute('placeholder'),
            aria_label: el.getAttribute('aria-label'),
            href: el.getAttribute('href'),
            visible: rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'
          };
        })
        """,
        max_elements,
    )
    elements = [InteractiveElement(**item) for item in raw_elements]
    return PageSnapshot(
        url=page.url,
        title=title,
        text=text,
        interactive_elements=elements,
        console_messages=console_messages or [],
        metadata={"element_count": len(elements)},
    )
