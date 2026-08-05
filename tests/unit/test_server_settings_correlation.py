"""关联网关前缀映射配置（ServerSettings.correlation_*）单元测试。"""

from __future__ import annotations

from pathlib import Path

from argus_py.config.server_settings import ServerSettings, load_server_settings


def _write_config(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_defaults_are_empty() -> None:
    """默认不启用网关前缀映射。"""
    settings = load_server_settings()
    assert settings.correlation_gateway_strip_prefixes == []
    assert settings.correlation_gateway_prepend_prefix == ""


def test_parses_correlation_gateway_mapping(tmp_path: Path) -> None:
    """correlation 段配置正确解析 strip_prefixes / prepend_prefix。"""
    cfg = _write_config(
        tmp_path / "server.yaml",
        """
server:
  host: 127.0.0.1
correlation:
  gateway_strip_prefixes: ["/api", "/legacy"]
  gateway_prepend_prefix: "/v1"
""",
    )
    settings = load_server_settings(cfg)
    assert settings.correlation_gateway_strip_prefixes == ["/api", "/legacy"]
    assert settings.correlation_gateway_prepend_prefix == "/v1"


def test_strip_prefixes_accepts_comma_string(tmp_path: Path) -> None:
    """strip_prefixes 支持逗号分隔字符串形式。"""
    cfg = _write_config(
        tmp_path / "server.yaml",
        """
correlation:
  gateway_strip_prefixes: "/api,/v2"
""",
    )
    settings = load_server_settings(cfg)
    assert settings.correlation_gateway_strip_prefixes == ["/api", "/v2"]


def test_settings_fields_exist() -> None:
    """ServerSettings dataclass 声明两个字段（防拼写漂移）。"""
    assert "correlation_gateway_strip_prefixes" in ServerSettings.__dataclass_fields__
    assert "correlation_gateway_prepend_prefix" in ServerSettings.__dataclass_fields__
