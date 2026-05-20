"""验证 ws.py 内部工具函数：
- _parse_since_seq 的查询参数解析
- _is_origin_allowed 的 CORS 校验
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

from argus_py.api.routes.ws import _is_origin_allowed, _parse_since_seq


def _fake_ws(
    query_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> Mock:
    """构造一个暴露 query_params 与 headers 的伪 WebSocket。"""
    ws = Mock(spec=[])

    class _FakeQueryParams:
        def __init__(self, data: dict[str, str]) -> None:
            self._data = data

        def get(self, key: str, default: Any = None) -> Any:
            return self._data.get(key, default)

    class _FakeHeaders:
        def __init__(self, data: dict[str, str]) -> None:
            self._data = {k.lower(): v for k, v in data.items()}

        def get(self, key: str, default: Any = None) -> Any:
            return self._data.get(key.lower(), default)

    ws.query_params = _FakeQueryParams(query_params or {})
    ws.headers = _FakeHeaders(headers or {})
    return ws


@dataclass(frozen=True)
class _FakeSettings:
    """构造 _is_origin_allowed 需要的最小 settings 形状。"""

    cors_allow_origins: list[str]


class TestParseSinceSeq:
    def test_parses_valid_int(self) -> None:
        ws = _fake_ws({"sinceSeq": "42"})
        assert _parse_since_seq(ws) == 42

    def test_returns_none_when_missing(self) -> None:
        ws = _fake_ws({})
        assert _parse_since_seq(ws) is None

    def test_returns_none_on_empty_string(self) -> None:
        ws = _fake_ws({"sinceSeq": ""})
        assert _parse_since_seq(ws) is None

    def test_returns_none_on_non_numeric(self) -> None:
        ws = _fake_ws({"sinceSeq": "not-a-number"})
        assert _parse_since_seq(ws) is None

    def test_parses_zero(self) -> None:
        ws = _fake_ws({"sinceSeq": "0"})
        assert _parse_since_seq(ws) == 0


class TestIsOriginAllowed:
    """私网部署：WebSocket 必须只接受 CORS 白名单内的 Origin。"""

    def test_no_origin_header_allowed(self, monkeypatch) -> None:
        """无 Origin（CLI / 服务器到服务器）应放行。"""
        monkeypatch.setattr(
            "argus_py.api.routes.ws.load_server_settings",
            lambda: _FakeSettings(cors_allow_origins=["http://localhost:8000"]),
        )
        ws = _fake_ws(headers={})
        assert _is_origin_allowed(ws) is True

    def test_origin_in_allow_list(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "argus_py.api.routes.ws.load_server_settings",
            lambda: _FakeSettings(cors_allow_origins=["http://localhost:8000"]),
        )
        ws = _fake_ws(headers={"origin": "http://localhost:8000"})
        assert _is_origin_allowed(ws) is True

    def test_origin_not_in_allow_list(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "argus_py.api.routes.ws.load_server_settings",
            lambda: _FakeSettings(cors_allow_origins=["http://localhost:8000"]),
        )
        ws = _fake_ws(headers={"origin": "http://evil.internal:8080"})
        assert _is_origin_allowed(ws) is False

    def test_wildcard_allows_any(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "argus_py.api.routes.ws.load_server_settings",
            lambda: _FakeSettings(cors_allow_origins=["*"]),
        )
        ws = _fake_ws(headers={"origin": "http://anywhere.example.com"})
        assert _is_origin_allowed(ws) is True

    def test_settings_load_failure_denies(self, monkeypatch) -> None:
        """配置读取失败时按拒绝处理，避免意外打开门户。"""

        def _boom() -> None:
            raise RuntimeError("settings broken")

        monkeypatch.setattr("argus_py.api.routes.ws.load_server_settings", _boom)
        ws = _fake_ws(headers={"origin": "http://localhost:8000"})
        assert _is_origin_allowed(ws) is False
