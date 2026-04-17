"""Playwright client wrapper."""

import asyncio
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from argus_py.browser.errors import BrowserError


class PlaywrightClient:
    """Manages Playwright browser lifecycle.

    Usage:
        async with PlaywrightClient() as client:
            page = await client.new_page()
            await page.goto("https://example.com")
    """

    def __init__(self, headless: bool = False, browser_type: str = "chromium"):
        self.headless = headless
        self.browser_type = browser_type
        self._playwright = None
        self._browser: Optional[Browser] = None

    async def start(self):
        """Launch the browser instance."""
        # TODO: implement with async_playwright()
        raise NotImplementedError("PlaywrightClient.start() not yet implemented")

    async def stop(self):
        """Close the browser instance."""
        # TODO: implement browser.close()
        raise NotImplementedError("PlaywrightClient.stop() not yet implemented")

    async def new_page(self) -> Page:
        """Create a new browser page."""
        # TODO: implement browser.new_page()
        raise NotImplementedError("PlaywrightClient.new_page() not yet implemented")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
