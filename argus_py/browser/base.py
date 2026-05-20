"""浏览器会话抽象。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page
from playwright.async_api import ConsoleMessage as PwConsoleMessage

from argus_py.browser.actions import BrowserActions
from argus_py.browser.constants import (
    DEFAULT_PAGE_READY_TIMEOUT_MS,
    DEFAULT_PAGE_SETTLE_MS,
    DEFAULT_SCREENSHOTS_DIR,
)
from argus_py.browser.errors import BrowserActionError, BrowserNotStartedError
from argus_py.browser.playwright_client import PlaywrightClient
from argus_py.browser.snapshot import ConsoleMessage, PageSnapshot, capture_snapshot


class BrowserSession:
    """封装一次测试任务内的浏览器上下文、页面、动作和观察。"""

    def __init__(
        self,
        client: PlaywrightClient | None = None,
        screenshot_dir: str | Path = DEFAULT_SCREENSHOTS_DIR,
        context_options: dict[str, Any] | None = None,
        page_ready_timeout_ms: int = DEFAULT_PAGE_READY_TIMEOUT_MS,
        page_settle_ms: int = DEFAULT_PAGE_SETTLE_MS,
        stop_browser: bool = True,
    ) -> None:
        self.client = client or PlaywrightClient()
        self.screenshot_dir = Path(screenshot_dir)
        self.context_options = context_options or {}
        self.page_ready_timeout_ms = page_ready_timeout_ms
        self.page_settle_ms = page_settle_ms
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.actions: BrowserActions | None = None
        self.console_messages: list[ConsoleMessage] = []
        self._stop_browser = stop_browser

    async def start(self) -> "BrowserSession":
        """启动浏览器会话。"""
        await self.client.start()
        self.context = await self.client.new_context(**self.context_options)
        self.page = await self.client.new_page(self.context)
        self.page.on("console", self._on_console)
        self.actions = BrowserActions(
            self.page,
            screenshot_dir=self.screenshot_dir,
            page_ready_timeout_ms=self.page_ready_timeout_ms,
            page_settle_ms=self.page_settle_ms,
        )
        return self

    async def stop(self) -> None:
        """关闭浏览器会话。

        当 ``stop_browser=False`` 时（复用进程级单例的场景），只关闭上下文，
        不会关闭共享的浏览器进程。
        """
        errors: list[Exception] = []
        try:
            if self.context is not None:
                await self.client.close_context(self.context)
        except Exception as exc:
            errors.append(exc)
        finally:
            self.context = None
            self.page = None
            self.actions = None

        if self._stop_browser:
            try:
                await self.client.stop()
            except Exception as exc:
                errors.append(exc)

        if errors:
            raise BrowserActionError("stop_session", "; ".join(str(item) for item in errors))

    def require_page(self) -> Page:
        """返回当前页面，未启动时抛出异常。"""
        if self.page is None:
            raise BrowserNotStartedError("BrowserSession 尚未启动。")
        return self.page

    def require_actions(self) -> BrowserActions:
        """返回动作封装，未启动时抛出异常。"""
        if self.actions is None:
            raise BrowserNotStartedError("BrowserSession 尚未启动。")
        return self.actions

    async def goto(self, url: str) -> dict[str, Any]:
        """打开页面。"""
        return await self.require_actions().navigate(url)

    async def click(self, target: str) -> dict[str, Any]:
        """点击元素。"""
        return await self.require_actions().click(target)

    async def fill(self, target: str, text: str) -> dict[str, Any]:
        """填写输入框。"""
        return await self.require_actions().fill(target, text)

    async def screenshot(self, name: str, full_page: bool = True) -> Path:
        """保存截图。"""
        return await self.require_actions().screenshot(name, full_page=full_page)

    async def snapshot(self) -> PageSnapshot:
        """获取页面快照，包含已收集的控制台消息，采集后清空消息避免跨步骤污染。"""
        await self.require_actions().wait_for_page_ready(require_load=False)
        messages = list(self.console_messages)
        self.console_messages.clear()
        return await capture_snapshot(self.require_page(), console_messages=messages)

    def _on_console(self, message: PwConsoleMessage) -> None:
        page_url = self.page.url if self.page else ""
        self.console_messages.append(
            ConsoleMessage(level=message.type, text=message.text, page_url=page_url)
        )

    async def __aenter__(self) -> "BrowserSession":
        return await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()
