"""HTML 清洗管线：删除脚本/样式、属性过滤、空白压缩、敏感值脱敏。"""

from __future__ import annotations

import re

from argus_py.redaction.core import redact_href
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


def clean_html_for_prompt(html: str) -> str:
    """清洗 HTML：删除脚本、样式，保留关键结构属性，敏感字段和超长值脱敏。"""
    html = _remove_block_tags(html)
    html = re.sub(r"<(\w+)((?:\s[^>]*)?)>", _filter_element_attributes, html)
    return _compress_whitespace(html)


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
    """清洗单个 HTML 标签的属性：只保留 _KEEP_ATTRS / aria-*，class 截断，value 脱敏。"""
    tag_start = match.group(1)
    attrs_str = match.group(2)
    if not attrs_str.strip():
        return match.group(0)

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


def _escape_attr_value(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
