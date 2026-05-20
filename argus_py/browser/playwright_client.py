"""Playwright 生命周期封装。"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from argus_py.browser.constants import (
    DEFAULT_ACTION_TIMEOUT_MS,
    DEFAULT_NAVIGATION_TIMEOUT_MS,
)
from argus_py.browser.errors import BrowserActionError, BrowserNotStartedError
from argus_py.core.constants import DEFAULT_BROWSER, DEFAULT_HEADLESS


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

    @property
    def is_started(self) -> bool:
        """浏览器是否已经启动。"""
        return self._browser is not None

    async def start(self) -> "PlaywrightClient":
        """启动浏览器。"""
        if self._browser is not None:
            return self
        try:
            self._playwright = await async_playwright().start()
            launcher = getattr(self._playwright, self.browser_type, None)
            if launcher is None:
                raise ValueError(f"不支持的浏览器类型：{self.browser_type}")
            options = {"headless": self.headless, **self.launch_options}
            self._browser = await launcher.launch(**options)
        except Exception as exc:
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            raise BrowserActionError("start_browser", str(exc), self.browser_type) from exc
        return self

    async def stop(self) -> None:
        """关闭浏览器并释放 Playwright。"""
        errors: list[Exception] = []
        for context in list(self._contexts):
            try:
                await context.close()
            except Exception as exc:
                errors.append(exc)
        self._contexts.clear()
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:
                errors.append(exc)
            finally:
                self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:
                errors.append(exc)
            finally:
                self._playwright = None
        if errors:
            raise BrowserActionError("stop_browser", "; ".join(str(item) for item in errors))

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
        if context in self._contexts:
            self._contexts.remove(context)

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
