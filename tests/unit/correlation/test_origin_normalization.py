"""阶段三：origin 同类判断回归 — 防止 parsed.host 为 None 导致跨域请求同源。"""

from __future__ import annotations

from argus_py.correlation.path_utils import extract_origin


class TestOriginCrossDomainRegression:
    """P0 回归：不同域名的 origin 必须不同。"""

    def test_distinct_hosts_not_equal(self) -> None:
        a = extract_origin("https://api.github.com/repos/test/repo")
        b = extract_origin("https://login.github.com/oauth")
        assert a != b
        assert a == "https://api.github.com"
        assert b == "https://login.github.com"

    def test_subdomain_vs_root(self) -> None:
        a = extract_origin("https://example.com/page")
        b = extract_origin("https://sub.example.com/page")
        assert a != b

    def test_fully_qualified_domains(self) -> None:
        a = extract_origin("https://www.google.com/search")
        b = extract_origin("https://mail.google.com/mail")
        assert a != b

    def test_port_difference(self) -> None:
        a = extract_origin("http://localhost:3000/api")
        b = extract_origin("http://localhost:8080/api")
        assert a != b

    def test_same_origin_different_paths(self) -> None:
        a = extract_origin("https://api.example.com/v1/users")
        b = extract_origin("https://api.example.com/v2/orders")
        assert a == b == "https://api.example.com"


class TestOriginEdgeCases:
    """边界场景。"""

    def test_ipv4_origin(self) -> None:
        a = extract_origin("https://192.168.1.1/admin")
        b = extract_origin("https://192.168.1.2/admin")
        assert a != b
        assert a == "https://192.168.1.1"
        assert b == "https://192.168.1.2"

    def test_same_ip_same_origin(self) -> None:
        a = extract_origin("http://127.0.0.1:5000/a")
        b = extract_origin("http://127.0.0.1:5000/b")
        assert a == b

    def test_http_vs_https_same_host(self) -> None:
        """不同 scheme 视为不同 origin。"""
        a = extract_origin("http://example.com/a")
        b = extract_origin("https://example.com/a")
        assert a != b
