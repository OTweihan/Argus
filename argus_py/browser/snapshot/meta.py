"""页面快照数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from argus_py.redaction.core import redact_href, redact_sensitive_text
from argus_py.redaction.patterns import _REDACTED, _is_sensitive


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
    resolved_url: str | None = None
    visible: bool = True
    disabled: bool = False
    checked: bool | None = None
    value: str | None = None
    required: bool = False
    selected_text: str | None = None

    # ── 工具函数 ──────────────────────────────────────────

    def selector_hint(self) -> str:
        """生成推荐给 LLM 使用的稳定定位表达式。"""
        label = (
            self.text or self.aria_label or self.placeholder or self.name or self.element_id or ""
        )
        if self.tag in {"input", "textarea", "select"} and self.name:
            return f'css=[name="{_escape_selector_value(self.name)}"]'
        if (
            self.tag in {"input", "textarea", "select"}
            and self.element_id
            and _is_simple_css_id(self.element_id)
        ):
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

    def redacted_value(self) -> str | None:
        """返回脱敏后的值。"""
        if self.value is None:
            return None
        if self.element_type == "hidden":
            return _REDACTED
        if _is_sensitive(self.element_type) or _is_sensitive(self.name):
            return _REDACTED
        return self.value

    def redacted_selected_text(self) -> str | None:
        """返回脱敏后的选中文本。"""
        if self.selected_text is None:
            return None
        if self.element_type == "hidden":
            return _REDACTED
        if _is_sensitive(self.element_type) or _is_sensitive(self.name):
            return _REDACTED
        return self.selected_text


@dataclass
class ConsoleMessage:
    """浏览器控制台消息。"""

    level: str
    text: str
    page_url: str = ""


@dataclass
class PageSnapshot:
    """页面观察结果。"""

    url: str
    title: str
    text: str
    interactive_elements: list[InteractiveElement] = field(default_factory=list)
    console_messages: list[ConsoleMessage] = field(default_factory=list)
    console_errors: list[ConsoleMessage] = field(default_factory=list)
    html_summary: str = ""
    accessibility_tree: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_prompt_text(self, max_elements: int = 40) -> str:
        """转换为适合传给 LLM 的紧凑文本。"""
        lines = [f"URL: {redact_href(self.url)}", f"Title: {self.title}"]

        if self.interactive_elements:
            lines.append("Interactive elements:")
            for item in self.interactive_elements[:max_elements]:
                label = redact_sensitive_text(
                    item.text
                    or item.aria_label
                    or item.placeholder
                    or item.name
                    or item.element_id
                    or ""
                )
                details = [
                    f"- [{item.index}] <{item.tag}>",
                    label,
                    f"selector={redact_sensitive_text(item.selector_hint())}",
                ]
                if item.element_type:
                    details.append(f"type={item.element_type}")
                if item.name:
                    details.append(f"name={item.name}")
                if item.href:
                    details.append(f"href={redact_href(item.href)}")
                if item.resolved_url and item.resolved_url != item.href:
                    details.append(f"resolved_url={redact_href(item.resolved_url)}")
                flags = []
                if item.disabled:
                    flags.append("disabled")
                if item.required:
                    flags.append("required")
                if item.checked is True:
                    flags.append("checked")
                rv = item.redacted_value()
                if rv is not None:
                    flags.append(f"value={rv}")
                rst = item.redacted_selected_text()
                if rst is not None:
                    flags.append(f"selected_text={rst}")
                if flags:
                    details.append(" ".join(flags))
                lines.append(" ".join(part for part in details if part).strip())

        if self.accessibility_tree:
            lines.append("Accessibility:")
            lines.append(redact_sensitive_text(self.accessibility_tree))

        lines.append("Visible text:")
        lines.append(redact_sensitive_text(self.text))

        if self.html_summary:
            lines.append("HTML summary:")
            lines.append(redact_sensitive_text(self.html_summary))

        if self.console_errors:
            lines.append("Console errors:")
            for msg in self.console_errors:
                lines.append(f"- [{msg.level}] {redact_sensitive_text(msg.text)}")

        return "\n".join(lines)


# ── 内部工具 ──────────────────────────────────────────────


def _escape_selector_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _is_simple_css_id(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in {"-", "_"} for char in value)
