"""浏览器高层动作封装。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from argus_py.browser.errors import BrowserActionError, BrowserError, BrowserTimeoutError
from argus_py.browser.selectors import SelectorQuery, require_visible
from argus_py.browser.snapshot import PageSnapshot, capture_snapshot
from argus_py.core.constants import (
    DEFAULT_ACTION_TIMEOUT_MS,
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    DEFAULT_PAGE_READY_TIMEOUT_MS,
    DEFAULT_PAGE_SETTLE_MS,
    DEFAULT_SCREENSHOTS_DIR,
)


class BrowserActions:
    """围绕单个 Page 的高层浏览器动作。"""

    def __init__(
        self,
        page: Page,
        screenshot_dir: str | Path = DEFAULT_SCREENSHOTS_DIR,
        action_timeout_ms: int = DEFAULT_ACTION_TIMEOUT_MS,
        navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
        page_ready_timeout_ms: int = DEFAULT_PAGE_READY_TIMEOUT_MS,
        page_settle_ms: int = DEFAULT_PAGE_SETTLE_MS,
    ) -> None:
        self.page = page
        self.screenshot_dir = Path(screenshot_dir)
        self.action_timeout_ms = action_timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms
        self.page_ready_timeout_ms = page_ready_timeout_ms
        self.page_settle_ms = page_settle_ms

    async def wait_for_page_ready(self, require_load: bool = False) -> dict[str, Any]:
        """等待页面进入相对稳定状态。"""
        try:
            if require_load:
                await self.page.wait_for_load_state("load", timeout=self.navigation_timeout_ms)
            else:
                await self.page.wait_for_load_state(
                    "domcontentloaded", timeout=self.page_ready_timeout_ms
                )
        except PlaywrightTimeoutError:
            # SPA、埋点或长连接页面可能迟迟不触发 load；保留后续截图和快照证据。
            pass

        try:
            await self.page.wait_for_function(
                "document.readyState === 'complete'",
                timeout=self.page_ready_timeout_ms,
            )
        except PlaywrightTimeoutError:
            # 某些页面会持续加载资源，调试命令不因此失败，后续截图仍保留证据。
            pass

        try:
            await self.page.wait_for_load_state("networkidle", timeout=self.page_ready_timeout_ms)
        except PlaywrightTimeoutError:
            # 长轮询、统计脚本或慢资源可能导致 networkidle 不出现，不能阻断测试。
            pass

        if self.page_settle_ms > 0:
            await asyncio.sleep(self.page_settle_ms / 1000)
        return {"url_after": self.page.url, "title": await self.page.title()}

    async def navigate(
        self,
        url: str,
        wait_until: Literal[
            "commit", "domcontentloaded", "load", "networkidle"
        ] = "domcontentloaded",
    ) -> dict[str, Any]:
        """打开页面并返回跳转前后状态。"""
        before = self.page.url
        try:
            response = await self.page.goto(
                url,
                wait_until=wait_until,
                timeout=self.navigation_timeout_ms,
            )
            ready_state = await self.wait_for_page_ready(require_load=True)
        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError(f"页面打开超时：{url}") from exc
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserActionError("navigate", str(exc), url) from exc
        return {
            "url_before": before,
            "url_after": ready_state["url_after"],
            "status": response.status if response else None,
            "title": ready_state["title"],
        }

    async def click(self, target: str | SelectorQuery) -> dict[str, Any]:
        """点击元素。"""
        before = self.page.url
        try:
            await self.wait_for_page_ready(require_load=False)
            locator = await require_visible(self.page, target, self.action_timeout_ms)
            await locator.click(timeout=self.action_timeout_ms)
            ready_state = await self.wait_for_page_ready(require_load=False)
        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError(f"点击超时：{target}") from exc
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserActionError("click", str(exc), str(target)) from exc
        return {
            "url_before": before,
            "url_after": ready_state["url_after"],
            "title": ready_state["title"],
        }

    async def fill(
        self, target: str | SelectorQuery, text: str, clear: bool = True
    ) -> dict[str, Any]:
        """填写输入框。"""
        try:
            await self.wait_for_page_ready(require_load=False)
            locator = await require_visible(self.page, target, self.action_timeout_ms)
            if clear:
                await locator.fill("", timeout=self.action_timeout_ms)
            await locator.fill(text, timeout=self.action_timeout_ms)
            ready_state = await self.wait_for_page_ready(require_load=False)
        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError(f"输入超时：{target}") from exc
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserActionError("fill", str(exc), str(target)) from exc
        return {"url_after": ready_state["url_after"], "title": ready_state["title"]}

    async def press(self, target: str | SelectorQuery, key: str) -> dict[str, Any]:
        """对元素发送按键。"""
        try:
            await self.wait_for_page_ready(require_load=False)
            locator = await require_visible(self.page, target, self.action_timeout_ms)
            await locator.press(key, timeout=self.action_timeout_ms)
            ready_state = await self.wait_for_page_ready(require_load=False)
        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError(f"按键超时：{target}") from exc
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserActionError("press", str(exc), str(target)) from exc
        return {"url_after": ready_state["url_after"], "title": ready_state["title"]}

    async def select_option(self, target: str | SelectorQuery, value: str) -> dict[str, Any]:
        """选择下拉框选项。"""
        try:
            await self.wait_for_page_ready(require_load=False)
            locator = await require_visible(self.page, target, self.action_timeout_ms)
            await locator.select_option(value, timeout=self.action_timeout_ms)
            ready_state = await self.wait_for_page_ready(require_load=False)
        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError(f"选择超时：{target}") from exc
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserActionError("select_option", str(exc), str(target)) from exc
        return {"url_after": ready_state["url_after"], "title": ready_state["title"]}

    async def wait(self, milliseconds: int) -> dict[str, Any]:
        """等待固定时间。"""
        await asyncio.sleep(milliseconds / 1000)
        return {"url_after": self.page.url, "title": await self.page.title()}

    async def wait_for_load_state(
        self, state: Literal["domcontentloaded", "load", "networkidle"] = "networkidle"
    ) -> dict[str, Any]:
        """等待页面加载状态。"""
        try:
            await self.page.wait_for_load_state(state, timeout=self.navigation_timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError(f"等待页面状态超时：{state}") from exc
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserActionError("wait_for_load_state", str(exc), state) from exc
        return {"url_after": self.page.url, "title": await self.page.title()}

    async def screenshot(self, name: str, full_page: bool = True) -> Path:
        """保存截图。"""
        target = self.screenshot_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self.wait_for_page_ready(require_load=False)
            await self.page.screenshot(path=str(target), full_page=full_page)
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserActionError("screenshot", str(exc), str(target)) from exc
        return target

    async def snapshot(self) -> PageSnapshot:
        """获取结构化页面快照。"""
        await self.wait_for_page_ready(require_load=False)
        return await capture_snapshot(self.page)

    async def current_state(self) -> dict[str, Any]:
        """获取页面基础状态。"""
        await self.wait_for_page_ready(require_load=False)
        return {"url": self.page.url, "title": await self.page.title()}
