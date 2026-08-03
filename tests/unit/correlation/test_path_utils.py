"""阶段三：路径规范化与脱敏 — 单元测试。"""

from __future__ import annotations

from argus_py.correlation.path_utils import (
    MAX_PATH_LENGTH,
    compute_config_digest,
    compute_path_segments,
    extract_origin,
    is_path_too_long,
    normalize_for_matching,
    sanitize_for_display,
    strip_longest_segment_prefix,
)


class TestExtractOrigin:
    """同源判断：hostname 读取、端口归一化、IPv6、blob/data 协议。"""

    def test_http_default_port_normalized(self) -> None:
        assert extract_origin("http://example.com:80/path") == "http://example.com"

    def test_https_default_port_normalized(self) -> None:
        assert extract_origin("https://example.com:443/path") == "https://example.com"

    def test_non_default_port_preserved(self) -> None:
        assert extract_origin("http://localhost:8080/api") == "http://localhost:8080"

    def test_hostname_lowercase(self) -> None:
        assert extract_origin("HTTPS://Example.COM/path") == "https://example.com"

    def test_different_hosts_different_origin(self) -> None:
        """P0 回归：不同域名不能被视为同源。"""
        o1 = extract_origin("https://api.example.com/v1")
        o2 = extract_origin("https://web.example.com/v2")
        assert o1 != o2
        assert o1 == "https://api.example.com"
        assert o2 == "https://web.example.com"

    def test_same_host_same_origin(self) -> None:
        o1 = extract_origin("https://example.com/api/users")
        o2 = extract_origin("https://example.com/api/orders")
        assert o1 == o2 == "https://example.com"

    def test_different_schemes_different_origin(self) -> None:
        o1 = extract_origin("http://example.com/")
        o2 = extract_origin("https://example.com/")
        assert o1 != o2

    def test_implicit_port_443(self) -> None:
        """HTTPS 未指定端口时 hostname 正确读取。"""
        assert extract_origin("https://example.com/x") == "https://example.com"

    def test_implicit_port_80(self) -> None:
        assert extract_origin("http://example.com/x") == "http://example.com"

    def test_non_standard_port(self) -> None:
        assert extract_origin("https://example.com:8443/x") == "https://example.com:8443"


class TestNormalizeForMatching:
    """路径规范化：重复斜杠、尾斜杠、matrix params、context path。"""

    def test_basic_path(self) -> None:
        assert normalize_for_matching("https://example.com/api/users") == "/api/users"

    def test_trailing_slash_removed(self) -> None:
        assert normalize_for_matching("https://example.com/api/users/") == "/api/users"

    def test_root_path_preserved(self) -> None:
        assert normalize_for_matching("https://example.com/") == "/"
        assert normalize_for_matching("https://example.com") == "/"

    def test_double_slash_merged(self) -> None:
        assert normalize_for_matching("https://example.com//api//v1//users") == "/api/v1/users"

    def test_query_and_fragment_removed(self) -> None:
        assert normalize_for_matching("https://example.com/api?q=1#section") == "/api"

    def test_matrix_param_removed(self) -> None:
        assert (
            normalize_for_matching("https://example.com/api;jsessionid=abc123/users")
            == "/api/users"
        )

    def test_context_path_stripped(self) -> None:
        assert (
            normalize_for_matching("https://example.com/app/api/users", context_path="/app")
            == "/api/users"
        )

    def test_context_path_root_fallback(self) -> None:
        """Context path 等于整个路径时返回 /"""
        assert normalize_for_matching("https://example.com/app", context_path="/app") == "/"

    def test_strip_prefixes_segment_boundary(self) -> None:
        """前缀剥离按段边界，/api/order 不匹配 /api/orders/1。"""
        path, hit = strip_longest_segment_prefix("/api/gateway/users", ["/api/gateway"])
        assert path == "/users"
        assert hit == "/api/gateway"

    def test_strip_prefixes_segment_boundary_no_false_match(self) -> None:
        """单段 /api/order 不应匹配 /api/orders/1。"""
        path, hit = strip_longest_segment_prefix("/api/order/123", ["/api/orders"])
        assert hit is None

    def test_prepend_prefix(self) -> None:
        result = normalize_for_matching("https://example.com/users", prepend_prefix="/gateway")
        assert result == "/gateway/users"

    def test_nfc_normalization(self) -> None:
        """Unicode NFC 归一化。"""
        # é as composed (NFC) vs decomposed (NFD)
        composed = "https://example.com/café"  # NFC
        assert normalize_for_matching(composed) == "/café"

    def test_empty_path_with_query(self) -> None:
        result = normalize_for_matching("https://example.com?query=1")
        assert result == "/"


class TestSanitizeForDisplay:
    """路径脱敏：UUID/hex token/email/base64 段替换。"""

    def test_uuid_segment_replaced(self) -> None:
        result = sanitize_for_display("/api/users/550e8400-e29b-41d4-a716-446655440000")
        assert result == "/api/users/{uuid}"

    def test_long_hex_replaced(self) -> None:
        result = sanitize_for_display("/files/abcdef0123456789abcdef0123456789abcdef")
        assert result == "/files/{token}"

    def test_base64_replaced(self) -> None:
        result = sanitize_for_display(
            "/download/dGVzdC1iYXNlNjQtZW5jb2RlZC1zdHJpbmctdGhhdC1pcy1sb25nLWVub3VnaA=="
        )
        assert result == "/download/{token}"

    def test_normal_segments_preserved(self) -> None:
        result = sanitize_for_display("/api/v1/users/42/orders")
        assert result == "/api/v1/users/42/orders"

    def test_empty_path(self) -> None:
        assert sanitize_for_display("") == ""

    def test_root_path(self) -> None:
        # / 分片后得 ['', '']，脱敏后 join 仍是 "/"
        assert sanitize_for_display("/") == "/"


class TestIsPathTooLong:
    def test_within_limit(self) -> None:
        assert not is_path_too_long("/short")

    def test_exceeds_default_limit(self) -> None:
        long_path = "/" + "a" * (MAX_PATH_LENGTH + 1)
        assert is_path_too_long(long_path)

    def test_custom_limit(self) -> None:
        assert is_path_too_long("/ab", max_length=2)  # len 3 > 2
        assert not is_path_too_long("/a", max_length=2)  # len 2 <= 2


class TestComputePathSegments:
    def test_normal_path(self) -> None:
        assert compute_path_segments("/api/v1/users") == ["api", "v1", "users"]

    def test_root_path(self) -> None:
        assert compute_path_segments("/") == []

    def test_empty_path(self) -> None:
        assert compute_path_segments("") == []


class TestComputeConfigDigest:
    def test_deterministic(self) -> None:
        d1 = compute_config_digest("v1", "v1")
        d2 = compute_config_digest("v1", "v1")
        assert d1 == d2

    def test_different_versions_different_hash(self) -> None:
        d1 = compute_config_digest("v1", "v1")
        d2 = compute_config_digest("v2", "v1")
        assert d1 != d2

    def test_length_is_16(self) -> None:
        assert len(compute_config_digest("v1", "v1")) == 16


class TestStripLongestSegmentPrefix:
    """最长前缀剥离。"""

    def test_exact_match(self) -> None:
        path, hit = strip_longest_segment_prefix("/api/gateway/users", ["/api/gateway"])
        assert path == "/users"
        assert hit == "/api/gateway"

    def test_segment_boundary_prevents_false_match(self) -> None:
        """P0 回归：前缀剥离不应产生段截断。"""
        path, hit = strip_longest_segment_prefix("/api/order/123", ["/api/orders"])
        assert hit is None

    def test_longest_prefix_wins(self) -> None:
        path, hit = strip_longest_segment_prefix(
            "/api/gateway/v2/users", ["/api", "/api/gateway", "/api/gateway/v2"]
        )
        assert path == "/users"
        assert hit == "/api/gateway/v2"

    def test_no_match(self) -> None:
        path, hit = strip_longest_segment_prefix("/app/users", ["/api"])
        assert hit is None
        assert path == "/app/users"

    def test_empty_prefixes(self) -> None:
        path, hit = strip_longest_segment_prefix("/api/users", [])
        assert hit is None
        assert path == "/api/users"
