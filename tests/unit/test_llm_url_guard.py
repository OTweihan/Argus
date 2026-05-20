"""LLM URL SSRF 防御单元测试。

覆盖私网部署语境下的关键拒绝/放行场景。
"""

from __future__ import annotations

import pytest

from argus_py.llm.url_guard import LLMUrlSafetyError, assert_llm_base_url_safe


class TestPublicHosts:
    """公网域名应放行。"""

    def test_openai(self) -> None:
        assert_llm_base_url_safe("https://api.openai.com/v1")

    def test_anthropic(self) -> None:
        assert_llm_base_url_safe("https://api.anthropic.com/v1")

    def test_dashscope(self) -> None:
        assert_llm_base_url_safe("https://dashscope.aliyuncs.com/compatible-mode/v1")


class TestSchemeRejection:
    """非 http/https scheme 必须拒绝。"""

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.com/",
            "gopher://example.com/",
            "javascript:alert(1)",
        ],
    )
    def test_invalid_scheme(self, url: str) -> None:
        with pytest.raises(LLMUrlSafetyError, match="http/https"):
            assert_llm_base_url_safe(url)


class TestMetadataRejection:
    """云 metadata 必须拒绝（AWS/GCP/Aliyun 都在 169.254.169.254）。"""

    def test_aws_ip(self) -> None:
        with pytest.raises(LLMUrlSafetyError, match="内网/特殊地址|metadata"):
            assert_llm_base_url_safe("http://169.254.169.254/latest/meta-data/")

    def test_gcp_internal(self) -> None:
        with pytest.raises(LLMUrlSafetyError, match="metadata"):
            assert_llm_base_url_safe("http://metadata.google.internal/")

    def test_metadata_short(self) -> None:
        with pytest.raises(LLMUrlSafetyError, match="metadata"):
            assert_llm_base_url_safe("http://metadata/")


class TestPrivateIpRejection:
    """RFC1918 私网默认拒绝。"""

    @pytest.mark.parametrize(
        "url",
        [
            "http://10.0.0.1/v1",
            "http://10.255.255.255/v1",
            "http://172.16.0.5/v1",
            "http://172.31.255.255/v1",
            "http://192.168.1.1/v1",
            "http://192.168.0.100:11434/v1",
        ],
    )
    def test_private_ip(self, url: str) -> None:
        with pytest.raises(LLMUrlSafetyError, match="内网/特殊地址"):
            assert_llm_base_url_safe(url)


class TestSpecialNetworks:
    """链路本地 / 保留段 / 组播默认拒绝。"""

    def test_link_local(self) -> None:
        with pytest.raises(LLMUrlSafetyError):
            assert_llm_base_url_safe("http://169.254.1.1/")

    def test_unspecified(self) -> None:
        with pytest.raises(LLMUrlSafetyError):
            assert_llm_base_url_safe("http://0.0.0.0/")

    def test_multicast(self) -> None:
        with pytest.raises(LLMUrlSafetyError):
            assert_llm_base_url_safe("http://239.0.0.1/")


class TestLocalhostDefaultAllow:
    """默认放行 localhost / 127.0.0.1（同机 Ollama 场景）。"""

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:11434/v1",
            "http://127.0.0.1:11434/v1",
        ],
    )
    def test_localhost_allowed(self, url: str) -> None:
        assert_llm_base_url_safe(url)


class TestInternalHostnames:
    """.local / .internal 内网域名默认拒绝。"""

    @pytest.mark.parametrize(
        "url",
        [
            "http://llm.internal/v1",
            "http://llm.example.internal/v1",
            "http://server.local/v1",
        ],
    )
    def test_internal_hostname(self, url: str) -> None:
        with pytest.raises(LLMUrlSafetyError, match="内网域名"):
            assert_llm_base_url_safe(url)


class TestAllowHostsBypass:
    """allow_hosts 白名单应能放行受限地址。"""

    def test_allow_private_ip(self) -> None:
        assert_llm_base_url_safe(
            "http://10.10.20.5:8080/v1",
            allow_hosts=["10.10.20.5"],
        )

    def test_allow_internal_hostname(self) -> None:
        assert_llm_base_url_safe(
            "http://llm.internal.example.com/v1",
            allow_hosts=["llm.internal.example.com"],
        )

    def test_allow_is_case_insensitive(self) -> None:
        assert_llm_base_url_safe(
            "http://LLM.Internal.Example.Com/v1",
            allow_hosts=["llm.internal.example.com"],
        )

    def test_allow_skips_metadata(self) -> None:
        """显式允许后即使是 metadata IP 也应放行（运维责任）。"""
        assert_llm_base_url_safe(
            "http://169.254.169.254/",
            allow_hosts=["169.254.169.254"],
        )


class TestEdgeCases:
    def test_empty_url_is_noop(self) -> None:
        assert_llm_base_url_safe("")
        assert_llm_base_url_safe(None)

    def test_missing_host(self) -> None:
        with pytest.raises(LLMUrlSafetyError, match="缺少主机名"):
            assert_llm_base_url_safe("http:///path-only")

    def test_whitespace_stripped(self) -> None:
        assert_llm_base_url_safe("  https://api.openai.com/v1  ")
