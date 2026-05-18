"""页面结构化快照。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page

from argus_py.redaction.core import redact_href, redact_sensitive_text
from argus_py.redaction.patterns import _REDACTED, _is_sensitive

_MAX_CLASS_LENGTH = 60

# HTML 属性清洗中保留的关键属性集合
_KEEP_ATTRS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "type",
        "role",
        "aria-label",
        "placeholder",
        "href",
        "value",
        "disabled",
        "checked",
        "required",
    }
)


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
        """
        (els, maxElements) => {
          const SENSITIVE = [
            'password','passwd','passcode','pwd','token','apikey','api_key',
            'secret','credential','session','jwt','authorization'
          ];
          const isSensitive = (name) => {
            if (!name) return false;
            const lower = name.toLowerCase();
            return SENSITIVE.some(p => lower.includes(p));
          };
          const redactValue = (el) => {
            if (el.type === 'hidden') return '[REDACTED]';
            if (isSensitive(el.type) || isSensitive(el.name)) return '[REDACTED]';
            return el.value || null;
          };
          const redactSelectedText = (el) => {
            if (el.type === 'hidden') return '[REDACTED]';
            if (isSensitive(el.type) || isSensitive(el.name)) return '[REDACTED]';
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
              const start = el.selectionStart;
              const end = el.selectionEnd;
              if (start !== null && end !== null && start !== end && el.value) {
                return el.value.substring(start, end).slice(0, 160);
              }
            } else if (el.tagName === 'SELECT' && el.selectedOptions && el.selectedOptions.length > 0) {
              return el.selectedOptions[0].textContent || null;
            }
            return null;
          };
          return els.slice(0, maxElements).map((el, index) => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return {
              index,
              tag: el.tagName.toLowerCase(),
              text: (el.innerText || el.getAttribute('placeholder') || el.getAttribute('name') || el.id || '').trim().slice(0, 160),
              role: el.getAttribute('role'),
              element_type: el.getAttribute('type'),
              name: el.getAttribute('name'),
              element_id: el.id || null,
              placeholder: el.getAttribute('placeholder'),
              aria_label: el.getAttribute('aria-label'),
              href: el.getAttribute('href'),
              resolved_url: (() => {
                const h = el.getAttribute('href');
                if (!h) return null;
                try { return new URL(h, window.location.href).href; } catch(e) { return null; }
              })(),
              visible: rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none',
              disabled: el.disabled || false,
              checked: (el.tagName === 'INPUT' && el.type === 'checkbox') ? el.checked : null,
              value: redactValue(el),
              required: el.required || false,
              selected_text: redactSelectedText(el)
            };
          });
        }
        """,
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
        cleaned = _clean_html_for_prompt(html)
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length] + "\n... [truncated]"
        return cleaned
    except Exception:
        return ""


def _remove_block_tags(html: str) -> str:
    """删除 script / style / svg / path / noscript 标签及其内容。"""
    html = re.sub(
        r"<(script|style|svg|path|noscript)\b[^>]*>.*?</\1>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    html = re.sub(r"<(script|style|svg|path|noscript)\b[^>]*/>", "", html, flags=re.IGNORECASE)
    return html


def _redact_attr_value(
    attr_name: str,
    attr_val: str,
    element_type: str,
    element_name: str,
) -> str:
    """对 value 属性按元素类型/名称决定是否脱敏，非 value 属性原样返回。"""
    if attr_name != "value":
        return attr_val
    if element_type == "hidden":
        return _REDACTED
    if _is_sensitive(element_type) or _is_sensitive(element_name):
        return _REDACTED
    return attr_val


def _filter_element_attributes(match: re.Match) -> str:
    """清洗单个 HTML 标签的属性：只保留 _KEEP_ATTRS / aria-*，class 截断，value 脱敏。

    match.group(1) = 标签名，match.group(2) = 属性字符串。
    """
    tag_start = match.group(1)
    attrs_str = match.group(2)
    if not attrs_str.strip():
        return match.group(0)

    # 解析已有属性：提取 type、name 用于脱敏判断
    parsed: dict[str, str] = {}
    for am in re.finditer(r'([\w-]+)\s*=\s*"([^"]*)"', attrs_str):
        parsed[am.group(1).lower()] = am.group(2)

    attrib_type = parsed.get("type", "")
    attrib_name = parsed.get("name", "")

    kept_parts: list[str] = []
    for attr_match in re.finditer(
        r'([\w-]+)\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)',
        attrs_str,
    ):
        raw_name = attr_match.group(1)
        name = raw_name.lower()
        raw_val = attr_match.group(2)

        if name == "class":
            val = raw_val.strip("\"'")
            if len(val) > _MAX_CLASS_LENGTH:
                val = val[:_MAX_CLASS_LENGTH] + "..."
            kept_parts.append(f'class="{_escape_attr_value(val)}"')
            continue

        if name in _KEEP_ATTRS:
            val = raw_val.strip("\"'")
            val = _redact_attr_value(name, val, attrib_type, attrib_name)
            if name == "href":
                val = redact_href(val)
            kept_parts.append(f'{raw_name}="{_escape_attr_value(val)}"')
        elif name.startswith("aria-"):
            val = raw_val.strip("\"'")
            kept_parts.append(f'{raw_name}="{_escape_attr_value(val)}"')

    return f"<{tag_start} {' '.join(kept_parts)}>" if kept_parts else f"<{tag_start}>"


def _compress_whitespace(html: str) -> str:
    """压缩 HTML 中的多余空白行和连续空格。"""
    html = re.sub(r"\n\s*\n", "\n", html)
    html = re.sub(r"  +", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def _clean_html_for_prompt(html: str) -> str:
    """清洗 HTML：删除脚本、样式，保留关键结构属性，敏感字段和超长值脱敏。"""
    html = _remove_block_tags(html)
    html = re.sub(r"<(\w+)((?:\s[^>]*)?)>", _filter_element_attributes, html)
    return _compress_whitespace(html)


async def _capture_accessibility_summary(page: Page, max_nodes: int = 80) -> str:
    """基于 DOM 属性生成轻量可访问性摘要，不依赖 Playwright accessibility API。"""
    try:
        raw = await page.evaluate(
            """
            (maxNodes) => {
              const els = document.querySelectorAll(
                'a,button,input,textarea,select,[role],summary,label,[aria-label]'
              );
              const results = [];
              for (const el of els) {
                if (results.length >= maxNodes) break;
                const tag = el.tagName.toLowerCase();
                const role = el.getAttribute('role') ||
                  (tag === 'a' ? 'link' : '') ||
                  (tag === 'button' ? 'button' : '') ||
                  (tag === 'input' ? (el.type === 'checkbox' ? 'checkbox' : el.type === 'radio' ? 'radio' : 'textbox') : '') ||
                  (tag === 'textarea' ? 'textbox' : '') ||
                  (tag === 'select' ? 'combobox' : '') ||
                  (tag === 'summary' ? 'button' : '') ||
                  '';
                const name = el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
                  (el.id ? (() => { try { const lbl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); return lbl ? lbl.innerText.trim() : ''; } catch(e) { return ''; } })() : '') ||
                  (tag === 'button' || tag === 'a' || tag === 'summary' ? (el.innerText || '').trim().slice(0, 80) : '') ||
                  '';
                const disabled = el.disabled || false;
                const checked = (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) ? el.checked : null;
                const required = el.required || false;
                const state = [];
                if (disabled) state.push('disabled');
                if (checked === true) state.push('checked');
                if (required) state.push('required');

                let line = '- role=' + (role || 'unknown');
                if (name) line += ' name="' + name + '"';
                if (state.length) line += ' [' + state.join(',') + ']';
                results.push(line);
              }
              return results.join('\\n');
            }
            """,
            max_nodes,
        )
        return raw or ""
    except Exception:
        return ""


def _escape_selector_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _escape_attr_value(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _is_simple_css_id(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in {"-", "_"} for char in value)
