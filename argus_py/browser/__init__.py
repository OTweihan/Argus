"""Playwright 浏览器封装。"""

from argus_py.browser.actions import BrowserActions
from argus_py.browser.base import BrowserSession
from argus_py.browser.errors import (
    BrowserActionError,
    BrowserNotStartedError,
    BrowserTimeoutError,
    ElementNotFoundError,
)
from argus_py.browser.playwright_client import PlaywrightClient
from argus_py.browser.selectors import SelectorQuery, css, label, placeholder, role, test_id, text, xpath
from argus_py.browser.snapshot import ConsoleMessage, InteractiveElement, PageSnapshot, capture_snapshot, redact_href, redact_sensitive_text, redact_step_params

__all__ = [
    "BrowserActions",
    "BrowserSession",
    "PlaywrightClient",
    "SelectorQuery",
    "css",
    "text",
    "role",
    "label",
    "placeholder",
    "test_id",
    "xpath",
    "PageSnapshot",
    "InteractiveElement",
    "ConsoleMessage",
    "capture_snapshot",
    "redact_href",
    "redact_sensitive_text",
    "redact_step_params",
    "BrowserActionError",
    "BrowserNotStartedError",
    "BrowserTimeoutError",
    "ElementNotFoundError",
]
