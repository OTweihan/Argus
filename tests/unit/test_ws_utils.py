"""验证 ws.py 内部工具函数：
- _parse_since_seq 的查询参数解析
- _is_origin_allowed 的 CORS 校验
- _coalesce_events 白名单式合并正确性
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest
from argus_py.api.routes.ws import _coalesce_events, _is_origin_allowed, _parse_since_seq
from argus_py.infra.events import TaskEvent


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

    @pytest.fixture(autouse=True)
    def _reset_cors_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """每测试前重置模块级缓存，避免跨测试污染。"""
        monkeypatch.setattr("argus_py.api.routes.ws._cors_origins_cache", None)

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


def _evt(event_type: str, task_id: str = "tk-1", i: int = 0) -> TaskEvent:
    """快捷创建 TaskEvent 用于 coalesce 测试。"""
    return TaskEvent(sequence=i, event_type=event_type, task_id=task_id, data={"i": i})


class TestCoalesceEvents:
    """_coalesce_events 白名单式合并正确性（C1 修复后）。"""

    def test_whitelist_coalesces_multiple_events(self) -> None:
        """白名单类型多个事件合并为最后一条。"""
        events = [
            _evt("task.progress", i=1),
            _evt("task.progress", i=2),
            _evt("task.progress", i=3),
        ]
        result = _coalesce_events(events)
        assert len(result) == 1
        assert result[0].data["i"] == 3

    def test_non_whitelist_all_kept(self) -> None:
        """非白名单类型全部保留，不合并。"""
        events = [
            _evt("step.complete", i=1),
            _evt("finding.added", i=2),
            _evt("log.append", i=3),
        ]
        result = _coalesce_events(events)
        assert len(result) == 3

    def test_mixed_types_whitelist_coalesced_non_whitelist_kept(self) -> None:
        """混合时白名单合并，非白名单全部保留。"""
        events = [
            _evt("task.progress", i=1),
            _evt("step.complete", i=2),
            _evt("task.progress", i=3),
            _evt("finding.added", i=4),
        ]
        result = _coalesce_events(events)
        assert len(result) == 3
        assert [e.event_type for e in result] == ["step.complete", "task.progress", "finding.added"]
        # task.progress 应合并为最后一条（i=3）
        assert result[1].data["i"] == 3

    def test_different_task_ids_coalesced_separately(self) -> None:
        """不同 task_id 的白名单事件各自合并。"""
        events = [
            _evt("task.progress", task_id="tk-1", i=1),
            _evt("task.progress", task_id="tk-2", i=1),
            _evt("task.progress", task_id="tk-1", i=2),
        ]
        result = _coalesce_events(events)
        assert len(result) == 2
        # tk-1 保留最后一条（i=2），tk-2 保留（i=1）
        tk1 = [e for e in result if e.task_id == "tk-1"]
        tk2 = [e for e in result if e.task_id == "tk-2"]
        assert len(tk1) == 1
        assert tk1[0].data["i"] == 2
        assert len(tk2) == 1
        assert tk2[0].data["i"] == 1

    def test_single_event_unchanged(self) -> None:
        """单个事件直接通过。"""
        e = _evt("task.progress")
        assert _coalesce_events([e]) == [e]

    def test_all_whitelist_types_recognized(self) -> None:
        """所有白名单类型都生效。"""
        for typ in ("task.progress", "step.update", "evaluator.thinking"):
            result = _coalesce_events([_evt(typ, i=1), _evt(typ, i=2)])
            assert len(result) == 1, f"{typ} 未被合并"
            assert result[0].data["i"] == 2

    def test_empty_input_returns_empty(self) -> None:
        """空列表返回空。"""
        assert _coalesce_events([]) == []
