"""``browser/snapshot/`` HTML 清洗 + 数据模型工具函数单测。"""

from __future__ import annotations

import re

from argus_py.browser.snapshot import (
    _compress_whitespace,
    _filter_element_attributes,
    _redact_attr_value,
    _remove_block_tags,
)
from argus_py.browser.snapshot.html_pipeline import _escape_attr_value, clean_html_for_prompt
from argus_py.browser.snapshot.meta import (
    InteractiveElement,
    PageSnapshot,
    _escape_selector_value,
    _is_simple_css_id,
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

    def test_removes_noscript(self):
        assert _remove_block_tags("<noscript>no</noscript><div>yes</div>") == "<div>yes</div>"


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

    def test_href_preserved(self):
        m = _make_attr_match('a href="https://example.com/login"')
        result = _filter_element_attributes(m)
        # href 应出现在输出中（脱敏行为由 redact_href 控制，不在本测试范围）
        assert 'href="' in result

    def test_sensitive_value_redacted(self):
        m = _make_attr_match('input type="text" name="password" value="mypass123"')
        result = _filter_element_attributes(m)
        assert "[REDACTED]" in result

    def test_class_escaped(self):
        m = _make_attr_match('div class="he said \\"hello\\""')
        result = _filter_element_attributes(m)
        assert "class=" in result


class TestCompressWhitespace:
    def test_collapses_blank_lines(self):
        assert _compress_whitespace("a\n\n\nb") == "a\nb"

    def test_collapses_double_spaces(self):
        assert _compress_whitespace("a  b   c") == "a b c"

    def test_strips_surrounding(self):
        assert _compress_whitespace("  hello  ") == "hello"

    def test_preserves_single_newlines(self):
        assert _compress_whitespace("line1\nline2") == "line1\nline2"

    def test_mixed_whitespace_collapsed(self):
        # 连续空白（含换行 + 空格）压缩为单个换行
        assert _compress_whitespace("a\n \nb") == "a\nb"


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
        result = clean_html_for_prompt(html)
        assert "script" not in result
        assert "style" not in result
        assert 'id="main"' in result
        assert "[REDACTED]" in result
        assert "data-x" not in result
        assert result.strip() == result

    def test_empty_html(self):
        assert clean_html_for_prompt("") == ""

    def test_no_body_tag(self):
        assert clean_html_for_prompt("<p>hello</p>") == "<p>hello</p>"

    def test_only_script(self):
        assert clean_html_for_prompt("<script>evil</script>") == ""


class TestEscapeAttrValue:
    def test_escapes_ampersand(self):
        assert _escape_attr_value("a&b") == "a&amp;b"

    def test_escapes_quote(self):
        assert _escape_attr_value('a"b') == "a&quot;b"

    def test_escapes_lt(self):
        assert _escape_attr_value("a<b") == "a&lt;b"

    def test_passthrough_plain(self):
        assert _escape_attr_value("hello") == "hello"


class TestEscapeSelectorValue:
    def test_escapes_backslash(self):
        assert _escape_selector_value("a\\b") == "a\\\\b"

    def test_escapes_double_quote(self):
        assert _escape_selector_value('a"b') == 'a\\"b'

    def test_passthrough_plain(self):
        assert _escape_selector_value("hello") == "hello"


class TestIsSimpleCssId:
    def test_alphanumeric(self):
        assert _is_simple_css_id("main-content_2") is True

    def test_empty(self):
        assert _is_simple_css_id("") is False

    def test_special_chars(self):
        assert _is_simple_css_id("main:content") is False

    def test_starts_with_number(self):
        assert _is_simple_css_id("123abc") is True  # valid per our simple check


class TestInteractiveElementSelectorHint:
    def test_input_with_name(self):
        el = InteractiveElement(index=0, tag="input", name="username")
        assert el.selector_hint() == 'css=[name="username"]'

    def test_input_with_simple_id(self):
        el = InteractiveElement(index=0, tag="input", element_id="login-btn")
        assert el.selector_hint() == "css=#login-btn"

    def test_input_with_complex_id(self):
        el = InteractiveElement(index=0, tag="input", element_id="123:abc")
        assert "css=#123" not in el.selector_hint()

    def test_password_type(self):
        el = InteractiveElement(index=0, tag="input", element_type="password")
        assert el.selector_hint() == 'css=input[type="password"]'

    def test_button_with_label(self):
        el = InteractiveElement(index=0, tag="button", text="提交")
        assert el.selector_hint() == 'role=button[name="提交"]'

    def test_link_with_label(self):
        el = InteractiveElement(index=0, tag="a", text="关于我们")
        assert el.selector_hint() == 'role=link[name="关于我们"]'

    def test_placeholder(self):
        el = InteractiveElement(index=0, tag="input", placeholder="请输入用户名")
        assert el.selector_hint() == "placeholder=请输入用户名"

    def test_fallback_to_tag(self):
        el = InteractiveElement(index=0, tag="span")
        assert el.selector_hint() == "span"


class TestInteractiveElementRedactedValue:
    def test_none_value(self):
        el = InteractiveElement(index=0, tag="input", value=None)
        assert el.redacted_value() is None

    def test_hidden_type(self):
        el = InteractiveElement(index=0, tag="input", value="secret", element_type="hidden")
        assert el.redacted_value() == "[REDACTED]"

    def test_sensitive_name(self):
        el = InteractiveElement(index=0, tag="input", value="tok123", name="api_key")
        assert el.redacted_value() == "[REDACTED]"

    def test_plain_value(self):
        el = InteractiveElement(index=0, tag="input", value="hello")
        assert el.redacted_value() == "hello"


class TestPageSnapshotToPromptText:
    def test_minimal_snapshot(self):
        snap = PageSnapshot(url="https://example.com", title="Test", text="visible text")
        text = snap.to_prompt_text()
        assert "URL: https://example.com" in text
        assert "Title: Test" in text
        assert "visible text" in text

    def test_includes_interactive_elements(self):
        snap = PageSnapshot(
            url="https://example.com",
            title="Test",
            text="hello",
            interactive_elements=[
                InteractiveElement(index=0, tag="button", text="Click"),
                InteractiveElement(index=1, tag="a", text="Link"),
            ],
        )
        text = snap.to_prompt_text()
        assert "<button>" in text
        assert "<a>" in text

    def test_respects_max_elements(self):
        snap = PageSnapshot(
            url="https://example.com",
            title="Test",
            text="hello",
            interactive_elements=[
                InteractiveElement(index=i, tag="button", text=str(i)) for i in range(10)
            ],
        )
        text = snap.to_prompt_text(max_elements=3)
        assert "<button>" in text
        # 只有前 3 个元素
        assert text.count("<button>") == 3

    def test_accessibility_tree_included(self):
        snap = PageSnapshot(
            url="https://example.com",
            title="Test",
            text="hello",
            accessibility_tree='- role=link name="Home"',
        )
        text = snap.to_prompt_text()
        assert "Accessibility:" in text
        assert "Home" in text

    def test_console_errors_included(self):
        from argus_py.browser.snapshot.meta import ConsoleMessage

        snap = PageSnapshot(
            url="https://example.com",
            title="Test",
            text="hello",
            console_errors=[ConsoleMessage(level="error", text="Cannot find")],
        )
        text = snap.to_prompt_text()
        assert "Console errors:" in text
        assert "Cannot find" in text


# ── helpers ──


def _make_attr_match(html_fragment: str) -> re.Match[str]:
    """用 regex 模拟 re.sub callback 收到的 ``re.Match``。"""
    m = re.match(r"<(\w+)((?:\s[^>]*)?)>", f"<{html_fragment}>")
    assert m is not None
    return m
