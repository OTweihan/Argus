"""Browser 进程级单例行为测试。

- shared_client() 进程唯一性
- stop_shared_client() 幂等
- is_started() 初始状态
"""

from __future__ import annotations

from argus_py.browser.playwright_client import PlaywrightClient
from argus_py.browser.singleton import _client, is_started, shared_client, stop_shared_client


class TestBrowserSingleton:
    def _reset(self) -> None:
        """每测试后重置全局单例。"""
        import argus_py.browser.singleton as _mod

        _mod._client = None

    def test_shared_client_returns_instance(self) -> None:
        self._reset()
        client = shared_client()
        assert isinstance(client, PlaywrightClient)
        assert client is shared_client()

    def test_shared_client_returns_same_instance(self) -> None:
        self._reset()
        c1 = shared_client()
        c2 = shared_client()
        assert c1 is c2

    def test_shared_client_params_only_first_call(self) -> None:
        self._reset()
        c1 = shared_client(headless=True, browser_type="chromium")
        c2 = shared_client(headless=False, browser_type="firefox")
        # 第二次调用忽略参数，返回与 c1 相同的实例
        assert c1 is c2

    async def test_stop_shared_client_idempotent(self) -> None:
        self._reset()
        # 多次 stop 应安全
        await stop_shared_client()
        await stop_shared_client()
        assert _client is None

    async def test_stop_shared_client_when_not_started(self) -> None:
        self._reset()
        # 从未创建 client 时调用 stop
        await stop_shared_client()
        assert _client is None

    async def test_is_started_false_when_not_started(self) -> None:
        self._reset()
        assert await is_started() is False

    def test_shared_client_returns_same_after_restart(self) -> None:
        self._reset()
        c1 = shared_client()
        import argus_py.browser.singleton as _mod

        _mod._client = None
        c2 = shared_client()
        assert c1 is not c2
        assert isinstance(c2, PlaywrightClient)
