"""Playwright 浏览器封装。

Playwright 是可选依赖。未安装时导入此模块会得到明确的 InstallError。
API-only 部署无需安装，需要 browser 功能时执行::

    pip install 'argus[browser]'
"""

try:
    from argus_py.browser.actions import BrowserActions
    from argus_py.browser.base import BrowserSession
    from argus_py.browser.errors import (
        BrowserActionError,
        BrowserNotStartedError,
        BrowserTimeoutError,
        ElementNotFoundError,
    )
    from argus_py.browser.playwright_client import PlaywrightClient
    from argus_py.browser.selectors import (
        SelectorQuery,
        css,
        label,
        placeholder,
        role,
        test_id,
        text,
        xpath,
    )
    from argus_py.browser.singleton import is_started as browser_is_started
    from argus_py.browser.singleton import shared_client, stop_shared_client
    from argus_py.browser.snapshot import (
        ConsoleMessage,
        InteractiveElement,
        PageSnapshot,
        capture_snapshot,
    )
    from argus_py.redaction import redact_href, redact_sensitive_text, redact_step_params
except ModuleNotFoundError as _e:
    if _e.name == "playwright":
        raise ImportError(
            "Playwright is required for browser features but not installed.\n"
            "Install with: pip install 'argus[browser]'"
        ) from _e
    raise

__all__ = [
    "BrowserActions",
    "BrowserSession",
    "PlaywrightClient",
    "SelectorQuery",
    "shared_client",
    "stop_shared_client",
    "browser_is_started",
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
