"""Playwright 生命周期封装。"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from argus_py.browser.constants import (
    DEFAULT_ACTION_TIMEOUT_MS,
    DEFAULT_NAVIGATION_TIMEOUT_MS,
)
from argus_py.browser.errors import BrowserActionError, BrowserNotStartedError
from argus_py.core.constants import DEFAULT_BROWSER, DEFAULT_HEADLESS

logger = logging.getLogger(__name__)


class PlaywrightClient:
    """管理 Playwright 浏览器生命周期。"""

    def __init__(
        self,
        headless: bool = DEFAULT_HEADLESS,
        browser_type: str = DEFAULT_BROWSER,
        launch_options: dict[str, Any] | None = None,
        context_options: dict[str, Any] | None = None,
        action_timeout_ms: int = DEFAULT_ACTION_TIMEOUT_MS,
        navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
    ) -> None:
        self.headless = headless
        self.browser_type = browser_type
        self.launch_options = launch_options or {}
        self.context_options = context_options or {}
        self.action_timeout_ms = action_timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: list[BrowserContext] = []
        self._connected: bool = False

    @property
    def is_started(self) -> bool:
        """浏览器是否已经启动且连接正常。"""
        return self._browser is not None and self._connected

    async def start(self) -> "PlaywrightClient":
        """启动浏览器。"""
        if self._browser is not None and self._connected:
            return self
        # 清理残留断开状态的浏览器
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                logger.warning("清理断开状态的浏览器失败", exc_info=True)
            self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.warning("清理断开状态的 Playwright 失败", exc_info=True)
            self._playwright = None
        try:
            self._playwright = await async_playwright().start()
            launcher = getattr(self._playwright, self.browser_type, None)
            if launcher is None:
                raise ValueError(f"不支持的浏览器类型：{self.browser_type}")
            options = {"headless": self.headless, **self.launch_options}
            self._browser = await launcher.launch(**options)
            self._connected = True
            self._browser.on("disconnected", lambda _: self._on_disconnected())
        except Exception as exc:
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            raise BrowserActionError("start_browser", str(exc), self.browser_type) from exc
        return self

    def _on_disconnected(self) -> None:
        """浏览器进程意外断开回调。"""
        self._connected = False
        logger.warning("浏览器进程意外断开 (%s)", self.browser_type)

    async def stop(self) -> None:
        """关闭浏览器并释放 Playwright。"""
        errors: list[Exception] = []
        self._connected = False
        for context in list(self._contexts):
            try:
                await context.close()
            except Exception as exc:
                errors.append(exc)
        self._contexts.clear()
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                logger.warning("stop() 关闭浏览器失败", exc_info=True)
            finally:
                self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.warning("stop() 关闭 Playwright 失败", exc_info=True)
            finally:
                self._playwright = None

    async def new_context(self, **context_options: Any) -> BrowserContext:
        """创建浏览器上下文。"""
        if self._browser is None:
            raise BrowserNotStartedError("PlaywrightClient 尚未启动。")
        options = {**self.context_options, **context_options}
        context = await self._browser.new_context(**options)
        context.set_default_timeout(self.action_timeout_ms)
        context.set_default_navigation_timeout(self.navigation_timeout_ms)
        self._contexts.append(context)
        return context

    async def close_context(self, context: BrowserContext) -> None:
        """关闭指定上下文。"""
        await context.close()
        try:
            self._contexts.remove(context)
        except ValueError:
            pass

    async def new_page(self, context: BrowserContext | None = None) -> Page:
        """创建新页面。"""
        if context is None:
            context = await self.new_context()
        page = await context.new_page()
        page.set_default_timeout(self.action_timeout_ms)
        page.set_default_navigation_timeout(self.navigation_timeout_ms)
        return page

    async def __aenter__(self) -> "PlaywrightClient":
        return await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()
