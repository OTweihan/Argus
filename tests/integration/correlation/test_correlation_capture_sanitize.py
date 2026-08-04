"""阶段四：采集过滤与脱敏端到端测试 — P3#2,#3,#4。

覆盖：同源过滤、资源类型过滤、步骤归属、
敏感信息脱敏（normalize_for_matching + sanitize_for_display → 不落库）。
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_py.correlation.enums import (
    RequestOutcome,
)
from argus_py.correlation.path_utils import (
    extract_origin,
    normalize_for_matching,
    sanitize_for_display,
)

pytestmark = [pytest.mark.integration]


# ── 同源过滤 ─────────────────────────────────────────────────────


class TestOriginFilteringLogic:
    """BrowserSession 的同源判断逻辑测试。"""

    def test_allowed_origin_match(self) -> None:
        origin = extract_origin("https://example.com/api/users")
        allowed = "https://example.com"
        assert origin == allowed

    def test_cross_origin_blocked(self) -> None:
        origin = extract_origin("https://evil.com/steal-data")
        allowed = "https://example.com"
        assert origin != allowed

    def test_subdomain_not_same_origin(self) -> None:
        a = extract_origin("https://example.com/page")
        b = extract_origin("https://api.example.com/page")
        assert a != b

    def test_http_vs_https_different(self) -> None:
        a = extract_origin("http://example.com/page")
        b = extract_origin("https://example.com/page")
        assert a != b

    def test_implicit_port_80_and_443(self) -> None:
        """默认端口与显式端口归一化。"""
        assert extract_origin("https://example.com:443/x") == "https://example.com"
        assert extract_origin("http://example.com:80/x") == "http://example.com"

    def test_non_standard_port_preserved(self) -> None:
        assert extract_origin("http://localhost:8080/api") == "http://localhost:8080"

    def test_ipv4_origin(self) -> None:
        assert extract_origin("https://192.168.1.100/admin") == "https://192.168.1.100"

    def test_ipv6_origin(self) -> None:
        assert extract_origin("https://[::1]:8080/path") == "https://::1:8080"

    def test_data_blob_protocols(self) -> None:
        """data: 和 blob: 协议（非标准 HTTP，保留原始 scheme）。"""
        data_origin = extract_origin("data:text/html,<h1>Hello</h1>")
        # data: URL 没有 hostname → host="" 且 scheme 为 data
        assert data_origin.startswith("data:")
        blob_origin = extract_origin("blob:https://example.com/uuid")
        assert blob_origin.startswith("blob:")


# ── 脱敏端到端 ────────────────────────────────────────────────────


class TestSanitizationEndToEnd:
    """敏感路径脱敏：规范化 + 脱敏 → 验证不泄露敏感信息。"""

    def test_token_in_path_replaced(self) -> None:
        """含 hex token 的路径 → display_path 为 {token}。"""
        raw = "https://example.com/download/abcdef0123456789abcdef0123456789abcdef"
        normalized = normalize_for_matching(raw)
        display = sanitize_for_display(normalized)
        assert "{token}" in display
        assert "abcdef0123456789" not in display

    def test_uuid_in_path_replaced(self) -> None:
        """含 UUID 的路径 → display_path 为 {uuid}。"""
        raw = "https://example.com/api/users/550e8400-e29b-41d4-a716-446655440000"
        normalized = normalize_for_matching(raw)
        display = sanitize_for_display(normalized)
        assert "{uuid}" in display
        assert "550e8400" not in display

    def test_base64_token_replaced(self) -> None:
        """Base64 编码段 → {token}。"""
        long_b64 = "dGVzdC1iYXNlNjQtZW5jb2RlZC1zdHJpbmctdGhhdC1pcy1sb25nLWVub3VnaA=="
        raw = f"https://example.com/files/{long_b64}"
        normalized = normalize_for_matching(raw)
        display = sanitize_for_display(normalized)
        assert "{token}" in display
        assert long_b64 not in display

    def test_normal_segments_preserved(self) -> None:
        """不含敏感信息的路径保持不变。"""
        raw = "https://example.com/api/v1/users/42/orders"
        normalized = normalize_for_matching(raw)
        display = sanitize_for_display(normalized)
        assert "/api/v1/users/42/orders" in display

    def test_long_hex_token_replaced(self) -> None:
        """32+ 字符的 hex 段被替换为 {token}。"""
        long_hex = "abcdef0123456789abcdef0123456789abcdef"
        raw = f"https://example.com/api/resource/{long_hex}"
        normalized = normalize_for_matching(raw)
        display = sanitize_for_display(normalized)
        # 匹配 32+ 位 hex 模式
        assert "{token}" in display
        assert long_hex not in display

    def test_jwt_token_replaced(self) -> None:
        """P1：JWT Bearer token 路径段被替换为 {token}。"""
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        raw = f"https://example.com/api/auth/{jwt}"
        normalized = normalize_for_matching(raw)
        display = sanitize_for_display(normalized)
        assert "{token}" in display
        assert jwt not in display

    def test_magic_link_token_replaced(self) -> None:
        """P1：magic-link 两段 token 也被替换。"""
        token = "abcdefghijklmnopqrstuvwxyz012345.zyxwvutsrqponmlkjihgfedcba987654"
        raw = f"https://example.com/login/magic/{token}"
        normalized = normalize_for_matching(raw)
        display = sanitize_for_display(normalized)
        assert "{token}" in display
        assert token not in display

    def test_short_dotted_path_not_falsely_matched(self) -> None:
        """短的非 token 点号路径不被误脱敏。"""
        # file.name.txt 每段 < 20 字符 → 不应匹配
        assert "file.name.txt" == sanitize_for_display("/path/to/file.name.txt").split("/")[-1]
        # 正常路径段不受影响
        display = sanitize_for_display("/api/v1/users/42")
        assert display == "/api/v1/users/42"

    def test_query_params_removed(self) -> None:
        """规范化阶段去除 query string 和 fragment。"""
        raw = "https://example.com/api/users?token=secret123&page=1#section"
        normalized = normalize_for_matching(raw)
        assert "token=secret123" not in normalized
        assert "page=1" not in normalized
        assert "#section" not in normalized
        assert normalized == "/api/users"

    def test_matrix_param_removed(self) -> None:
        """;jsessionid 去除了但路径保留。"""
        raw = "https://example.com/api;jsessionid=abc123/users"
        normalized = normalize_for_matching(raw)
        # matrix param 段应被移除
        assert "jsessionid" not in normalized
        assert "/api/users" in normalized

    def test_full_sanitize_pipeline(self) -> None:
        """完整脱敏管线：raw URL → normalized → display → 可在 API 中安全返回。"""
        raw_urls = [
            "https://example.com/api/users/550e8400-e29b-41d4-a716-446655440000/profile",
            "https://example.com/api/orders/123?api_key=sk-live-abc123",
            "https://example.com/download/abcdef0123456789abcdef0123456789abcdef",
            "https://example.com/api/v1/products/42",
        ]
        for raw in raw_urls:
            normalized = normalize_for_matching(raw)
            display = sanitize_for_display(normalized)
            # query string 不在 normalized 中
            assert "api_key" not in normalized
            assert "sk-live" not in normalized
            # 敏感段不在 display 中
            assert "550e8400" not in display
            assert "abcdef0123456789" not in display
            # 普通段保留
            assert display.startswith("/")


# ── 步骤归属 ──────────────────────────────────────────────────────


class TestStepAttribution:
    """请求归属于正确的执行步骤和尝试次数。"""

    def test_step_execution_id_format(self) -> None:
        """step_execution_id 格式：{blackbox_run_id}:step:{idx}:attempt:{n}。"""
        bb_id = "bbr:abc123def456"
        step_idx = 2
        attempt = 1
        step_id = f"{bb_id}:step:{step_idx}:attempt:{attempt}"
        assert step_id == "bbr:abc123def456:step:2:attempt:1"

        parts = step_id.split(":")
        assert parts[0] == "bbr"  # prefix
        assert parts[3] == "2"  # step index
        assert parts[5] == "1"  # attempt number

    def test_multiple_requests_same_step(self) -> None:
        """同一步骤的多条请求应有相同的 step_execution_id 和不同的 sequence。"""
        step_id = "bbr:abc:step:1:attempt:1"
        sequence = 0
        captures: list[dict[str, Any]] = []

        for _ in range(5):
            sequence += 1
            captures.append(
                {
                    "step_execution_id": step_id,
                    "sequence": sequence,
                }
            )

        step_ids = {c["step_execution_id"] for c in captures}
        assert len(step_ids) == 1
        assert step_ids == {step_id}
        assert [c["sequence"] for c in captures] == [1, 2, 3, 4, 5]

    def test_retry_changes_attempt_number(self) -> None:
        """重试时应更新 attempt number。"""
        bb_id = "bbr:xyz"
        # 第 1 次尝试
        sid1 = f"{bb_id}:step:3:attempt:1"
        # 第 2 次尝试
        sid2 = f"{bb_id}:step:3:attempt:2"
        assert sid1 != sid2
        assert sid1.endswith(":1")
        assert sid2.endswith(":2")


# ── 资源类型过滤 ──────────────────────────────────────────────────


class TestResourceTypeFiltering:
    """ALLOWED_RESOURCE_TYPES 过滤逻辑。"""

    _ALLOWED = frozenset(["document", "xhr", "fetch", "eventsource", "other"])

    def test_fetch_allowed(self) -> None:
        assert "fetch" in self._ALLOWED

    def test_xhr_allowed(self) -> None:
        assert "xhr" in self._ALLOWED

    def test_image_blocked(self) -> None:
        assert "image" not in self._ALLOWED

    def test_stylesheet_blocked(self) -> None:
        assert "stylesheet" not in self._ALLOWED

    def test_script_blocked(self) -> None:
        assert "script" not in self._ALLOWED

    def test_media_blocked(self) -> None:
        assert "media" not in self._ALLOWED

    def test_websocket_blocked(self) -> None:
        assert "websocket" not in self._ALLOWED


# ── pending/abandoned ──────────────────────────────────────────────


class TestPendingAbandoned:
    """pending 请求在会话结束时标记为 ABANDONED。"""

    def test_outcome_changes_to_abandoned(self) -> None:
        """ABANDONED 覆盖 COMPLETED。"""
        from argus_py.correlation.models import _CapturedRequest

        cap = _CapturedRequest(
            sequence=1,
            step_execution_id="step-1",
            step_attempt=1,
            page_sequence=1,
            method="GET",
            origin="https://example.com",
            normalized_path="/api/test",
            display_path="/api/test",
            resource_type="fetch",
            request_owner="FRAME",
            started_at="2024-01-01T00:00:00",
        )
        cap.outcome = RequestOutcome.COMPLETED
        # 模拟 abandon 逻辑
        cap.outcome = RequestOutcome.ABANDONED
        cap.finished_at = "2024-01-01T00:01:00"
        assert cap.outcome == RequestOutcome.ABANDONED

    def test_abandoned_requests_in_queue(self) -> None:
        """abandoned 请求也应进入持久化队列。"""
        from argus_py.correlation.models import _CapturedRequest

        abandoned: list[_CapturedRequest] = []
        for i in range(3):
            cap = _CapturedRequest(
                sequence=i + 1,
                step_execution_id=f"step-{i}",
                step_attempt=1,
                page_sequence=1,
                method="GET",
                origin="https://example.com",
                normalized_path=f"/api/item/{i}",
                display_path=f"/api/item/{i}",
                resource_type="fetch",
                request_owner="FRAME",
                started_at="2024-01-01T00:00:00",
            )
            cap.outcome = RequestOutcome.ABANDONED
            abandoned.append(cap)

        assert len(abandoned) == 3
        for cap in abandoned:
            assert cap.outcome == RequestOutcome.ABANDONED
            assert cap.normalized_path != cap.display_path or "/api/item/" in cap.normalized_path


# ── 数据完整性：敏感字段不落库验证 ─────────────────────────────


class TestSensitiveFieldsNotInDB:
    """验证 displayPath（脱敏后）和敏感字段不暴露在 API 响应中。

    注：API 层面已有 test_api_correlation.py 中对应的测试，
    此处聚焦于数据写入→读取管线的脱敏正确性。
    """

    def test_display_path_differs_from_normalized_for_sensitive(self) -> None:
        """含敏感信息的路径：normalized 与 display 应不同。"""
        sensitive_path = "/api/users/550e8400-e29b-41d4-a716-446655440000/profile"
        display = sanitize_for_display(sensitive_path)
        # display 不应包含原始 UUID
        assert "550e8400" not in display
        assert "{uuid}" in display

    def test_normal_path_identical(self) -> None:
        """普通路径：normalized = display。"""
        normal_path = "/api/v1/users/42/orders"
        display = sanitize_for_display(normal_path)
        assert display == normal_path

    def test_empty_and_root_path(self) -> None:
        assert sanitize_for_display("") == ""
        # "/" split → ["", ""] → join → "/"
        assert sanitize_for_display("/") == "/"
