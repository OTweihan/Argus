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
    def test_removes_query_string_and_fragment(self) -> None:
        assert redact_href("http://example.com/path?token=secret") == "http://example.com/path"
        assert redact_href("http://example.com/path#section") == "http://example.com/path"
        assert redact_href("http://example.com/path?q=1#s") == "http://example.com/path"

    def test_preserves_scheme_host_and_port(self) -> None:
        assert redact_href("https://example.com:8080/path") == "https://example.com:8080/path"

    def test_masks_javascript_and_data_uri(self) -> None:
        assert redact_href("javascript:alert(1)") == "javascript:[REDACTED]"
        assert "data:" in redact_href("data:text/html,<script>")
        assert "[REDACTED]" in redact_href("data:text/html,<script>")

    def test_handles_empty_and_fragment_only(self) -> None:
        assert redact_href("") == ""
        assert redact_href("#top") == "#top"

    def test_handles_non_http_schemes(self) -> None:
        result = redact_href("ftp://files.example.com/doc.pdf")
        assert result.startswith("ftp:")
        assert "[REDACTED]" in result


class TestRedactSensitiveText:
    def test_redacts_key_value_patterns(self) -> None:
        assert redact_sensitive_text("token=abc123") == "token=[REDACTED]"
        assert redact_sensitive_text("api_key=secret") == "api_key=[REDACTED]"

    def test_redacts_bearer_token(self) -> None:
        result = redact_sensitive_text("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9")
        assert "Bearer [REDACTED]" in result

    def test_redacts_json_patterns(self) -> None:
        result = redact_sensitive_text('"token":"my-secret-token"')
        assert '"token":"[REDACTED]"' in result

    def test_leaves_plain_text_unchanged(self) -> None:
        assert redact_sensitive_text("hello world") == "hello world"

    def test_leaves_non_sensitive_key_values(self) -> None:
        assert redact_sensitive_text("username=admin&action=login") == "username=admin&action=login"


class TestRedactStepParams:
    def test_redacts_url_params(self) -> None:
        result = redact_step_params({"url": "http://example.com?t=1"})
        assert result["url"] == "http://example.com"

    def test_redacts_sensitive_keys(self) -> None:
        result = redact_step_params({"password": "secret123"})
        assert result["password"] == "[REDACTED]"

    def test_redacts_value_when_selector_points_to_sensitive(self) -> None:
        result = redact_step_params({"selector": "input[name=password]", "value": "mypassword"})
        assert result["value"] == "[REDACTED]"

    def test_recursive_dict(self) -> None:
        result = redact_step_params({"nested": {"password": "secret"}})
        assert result["nested"]["password"] == "[REDACTED]"

    def test_recursive_list(self) -> None:
        result = redact_step_params({"items": [{"password": "secret"}]})
        assert result["items"][0]["password"] == "[REDACTED]"

    def test_list_of_urls(self) -> None:
        result = redact_step_params({"redirect_url": ["http://example.com?t=1"]})
        assert result["redirect_url"][0] == "http://example.com"

    def test_unchanged_for_plain_params(self) -> None:
        result = redact_step_params({"action": "click", "selector": "#btn"})
        assert result == {"action": "click", "selector": "#btn"}


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
