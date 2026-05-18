"""``browser/snapshot.py`` HTML 清洗工具函数单测。"""

from __future__ import annotations

import re

from argus_py.browser.snapshot import (
    _clean_html_for_prompt,
    _compress_whitespace,
    _filter_element_attributes,
    _redact_attr_value,
    _remove_block_tags,
)


class TestRemoveBlockTags:
    def test_removes_script_with_content(self):
        assert _remove_block_tags("<script>alert(1)</script>hello") == "hello"

    def test_removes_style_with_content(self):
        assert _remove_block_tags("<style>.x{color:red}</style><p>text</p>") == "<p>text</p>"

    def test_removes_self_closing(self):
        assert _remove_block_tags("<svg/><path/>") == ""

    def test_handles_case_insensitive(self):
        assert _remove_block_tags("<SCRIPT>void</SCRIPT>") == ""

    def test_preserves_unrelated_tags(self):
        assert _remove_block_tags("<div>keep</div>") == "<div>keep</div>"


class TestRedactAttrValue:
    def test_non_value_passthrough(self):
        assert _redact_attr_value("id", "my-id", "", "") == "my-id"

    def test_hidden_type_redacted(self):
        assert _redact_attr_value("value", "secret", "hidden", "") == "[REDACTED]"

    def test_sensitive_type_redacted(self):
        assert _redact_attr_value("value", "mypass", "password", "") == "[REDACTED]"

    def test_sensitive_name_redacted(self):
        assert _redact_attr_value("value", "tok", "text", "api_key") == "[REDACTED]"

    def test_plain_value_passthrough(self):
        assert _redact_attr_value("value", "hello", "text", "username") == "hello"


class TestFilterElementAttributes:
    def test_preserves_kept_attrs(self):
        m = _make_attr_match('input type="text" id="name" value="hello"')
        result = _filter_element_attributes(m)
        assert 'id="name"' in result
        assert 'value="hello"' in result

    def test_removes_class_when_within_limit(self):
        m = _make_attr_match('div class="short"')
        result = _filter_element_attributes(m)
        assert 'class="short"' in result

    def test_truncates_long_class(self):
        long_cls = "a" * 100
        m = _make_attr_match(f'div class="{long_cls}"')
        result = _filter_element_attributes(m)
        assert "..." in result
        assert len(result) < len(long_cls) + 20

    def test_strips_unknown_attrs(self):
        m = _make_attr_match('div data-x="foo" style="color:red" onclick="x"')
        result = _filter_element_attributes(m)
        assert "data-x" not in result
        assert "style" not in result
        assert "onclick" not in result

    def test_redacts_hidden_value(self):
        m = _make_attr_match('input type="hidden" value="secret"')
        result = _filter_element_attributes(m)
        assert "[REDACTED]" in result

    def test_empty_tag_no_attrs(self):
        m = _make_attr_match("br")
        result = _filter_element_attributes(m)
        assert result == "<br>"

    def test_aria_attrs_preserved(self):
        m = _make_attr_match('div aria-label="Close" aria-describedby="desc"')
        result = _filter_element_attributes(m)
        assert 'aria-label="Close"' in result
        assert 'aria-describedby="desc"' in result


class TestCompressWhitespace:
    def test_collapses_blank_lines(self):
        assert _compress_whitespace("a\n\n\nb") == "a\n\nb"

    def test_collapses_double_spaces(self):
        assert _compress_whitespace("a  b   c") == "a b c"

    def test_strips_surrounding(self):
        assert _compress_whitespace("  hello  ") == "hello"


class TestCleanHtmlForPrompt:
    def test_full_pipeline(self):
        html = """<html>
<head><style>.x{}</style></head>
<body>
<script>alert(1)</script>
<div class="long                 class" id="main" role="main" data-x="foo">
<input type="password" value="secret" name="pwd">
<a href="https://example.com">link</a>
</div>
</body>
</html>"""
        result = _clean_html_for_prompt(html)
        assert "script" not in result
        assert "style" not in result
        assert 'id="main"' in result
        assert "[REDACTED]" in result
        assert "data-x" not in result
        assert result.strip() == result


# ── helpers ──


def _make_attr_match(html_fragment: str) -> re.Match[str]:
    """用 regex 模拟 re.sub callback 收到的 ``re.Match``。"""
    m = re.match(r"<(\w+)((?:\s[^>]*)?)>", f"<{html_fragment}>")
    assert m is not None
    return m
