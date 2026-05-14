"""redaction 包单测：URL 脱敏、敏感文本脱敏、步骤参数脱敏、统一辅助函数。"""

from __future__ import annotations

import pytest

from argus_py.redaction import (
    redact_finding_entry,
    redact_href,
    redact_log_entry,
    redact_sensitive_text,
    redact_step_params,
)


class TestRedactHref:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("http://example.com/path?token=secret", "http://example.com/path"),
            ("http://example.com/path#section", "http://example.com/path"),
            ("http://example.com/path?q=1#s", "http://example.com/path"),
            ("https://example.com:8080/path", "https://example.com:8080/path"),
            ("", ""),
            ("#top", "#top"),
            ("javascript:alert(1)", "javascript:[REDACTED]"),
            ("data:text/html,<script>", "data:[REDACTED]"),
            ("ftp://files.example.com/doc.pdf", "ftp:[REDACTED]"),
        ],
        ids=[
            "query",
            "fragment",
            "both",
            "preserve_host_port",
            "empty",
            "fragment_only",
            "javascript",
            "data",
            "ftp",
        ],
    )
    def test_redact_href(self, url: str, expected: str) -> None:
        assert redact_href(url) == expected


class TestRedactSensitiveText:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("token=abc123", "token=[REDACTED]"),
            ("api_key=secret", "api_key=[REDACTED]"),
            (
                "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9",
                "Authorization: Bearer [REDACTED]",
            ),
            ('"token":"my-secret-token"', '"token":"[REDACTED]"'),
        ],
        ids=["key_value_token", "key_value_api_key", "bearer", "json"],
    )
    def test_redacts_sensitive_patterns(self, text: str, expected: str) -> None:
        assert redact_sensitive_text(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "hello world",
            "username=admin&action=login",
        ],
        ids=["plain", "non_sensitive_key_value"],
    )
    def test_leaves_plain_text(self, text: str) -> None:
        assert redact_sensitive_text(text) == text


class TestRedactStepParams:
    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"url": "http://example.com?t=1"}, {"url": "http://example.com"}),
            ({"password": "secret123"}, {"password": "[REDACTED]"}),
            (
                {"selector": "input[name=password]", "value": "mypassword"},
                {"selector": "input[name=password]", "value": "[REDACTED]"},
            ),
            ({"nested": {"password": "secret"}}, {"nested": {"password": "[REDACTED]"}}),
            (
                {"items": [{"password": "secret"}]},
                {"items": [{"password": "[REDACTED]"}]},
            ),
            (
                {"redirect_url": ["http://example.com?t=1"]},
                {"redirect_url": ["http://example.com"]},
            ),
            (
                {"action": "click", "selector": "#btn"},
                {"action": "click", "selector": "#btn"},
            ),
        ],
        ids=[
            "url",
            "sensitive_key",
            "selector_value",
            "recursive_dict",
            "recursive_list",
            "list_urls",
            "plain",
        ],
    )
    def test_redact_step_params(self, params: dict, expected: dict) -> None:
        assert redact_step_params(params) == expected


class TestRedactLogEntry:
    def test_redacts_all_log_fields(self) -> None:
        entry = {
            "params": {"password": "secret"},
            "url_before": "http://example.com?t=1",
            "url_after": "http://example.com#section",
            "screenshot_path": "/home/user/screenshots/step1.png",
            "message": "executed token=abc",
            "error": "failed api_key=xyz",
        }
        result = redact_log_entry(entry)
        assert result["params"]["password"] == "[REDACTED]"
        assert result["url_before"] == "http://example.com"
        assert result["url_after"] == "http://example.com"
        assert result["screenshot_path"] == "step1.png"
        assert "[REDACTED]" in result["message"]
        assert "[REDACTED]" in result["error"]

    def test_preserves_non_sensitive_log_fields(self) -> None:
        entry = {"action": "goto", "result": "success", "step_number": 1}
        result = redact_log_entry(entry)
        assert result["action"] == "goto"
        assert result["result"] == "success"
        assert result["step_number"] == 1

    def test_does_not_mutate_original(self) -> None:
        original = {"message": "token=abc"}
        result = redact_log_entry(original)
        assert original["message"] == "token=abc"
        assert result is not original


class TestRedactFindingEntry:
    def test_redacts_all_finding_fields(self) -> None:
        finding = {
            "url": "http://example.com?secret=1",
            "screenshot_path": "/tmp/screen.png",
            "title": "found token=abc",
            "description": "error api_key=xyz",
            "location": "div#main",
        }
        result = redact_finding_entry(finding)
        assert result["url"] == "http://example.com"
        assert result["screenshot_path"] == "screen.png"
        assert "[REDACTED]" in result["title"]
        assert "[REDACTED]" in result["description"]
        assert result["location"] == finding["location"]

    def test_does_not_mutate_original(self) -> None:
        original = {"title": "token=abc"}
        result = redact_finding_entry(original)
        assert original["title"] == "token=abc"
        assert result is not original
