"""验证 ws.py 内部工具函数：
- _parse_since_seq 的查询参数解析
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from argus_py.api.routes.ws import _parse_since_seq


def _fake_ws(query_params: dict[str, str]) -> Mock:
    """构造一个只暴露 query_params 属性的伪 WebSocket。"""
    ws = Mock(spec=[])

    class _FakeQueryParams:
        def __init__(self, data: dict[str, str]) -> None:
            self._data = data

        def get(self, key: str, default: Any = None) -> Any:
            return self._data.get(key, default)

    ws.query_params = _FakeQueryParams(query_params)
    return ws


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
