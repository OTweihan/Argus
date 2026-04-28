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

    def selector_hint(self) -> str:
        """生成推荐给 LLM 使用的稳定定位表达式。"""
        label = self.text or self.aria_label or self.placeholder or self.name or self.element_id or ""
        if self.tag in {"input", "textarea", "select"} and self.name:
            return f'css=[name="{_escape_selector_value(self.name)}"]'
        if self.tag in {"input", "textarea", "select"} and self.element_id and _is_simple_css_id(self.element_id):
            return f"css=#{self.element_id}"
        if self.tag == "input" and self.element_type == "password":
            return 'css=input[type="password"]'
        if self.tag == "button" and label:
            return f'role=button[name="{_escape_selector_value(label)}"]'
        if self.tag == "a" and label:
            return f'role=link[name="{_escape_selector_value(label)}"]'
        if self.placeholder:
            return f"placeholder={self.placeholder}"
        if self.aria_label:
            return f"label={self.aria_label}"
        if self.name:
            return f'css=[name="{_escape_selector_value(self.name)}"]'
        if self.element_id and _is_simple_css_id(self.element_id):
            return f"css=#{self.element_id}"
        if label:
            return f"text={label}"
        return self.tag


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
            details = [
                f"- [{item.index}] <{item.tag}>",
                label,
                f"selector={item.selector_hint()}",
            ]
            if item.element_type:
                details.append(f"type={item.element_type}")
            if item.name:
                details.append(f"name={item.name}")
            lines.append(" ".join(part for part in details if part).strip())
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


def _escape_selector_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _is_simple_css_id(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in {"-", "_"} for char in value)
