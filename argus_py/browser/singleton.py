"""Playwright 进程级单例管理。

维护进程内唯一的 PlaywrightClient/Browser 实例。各任务只创建/关闭
BrowserContext，避免重复 async_playwright().start() + browser.launch()
（1-3s+ 启动开销），同时降低并发任务内存占用。

浏览器进程意外崩溃时自动检测并重启，无需人工介入。

使用方式
--------
::

    # sync 工厂（最常见 —— BrowserSession 工厂场景）
    client = shared_client(headless=True, browser_type="chromium")

    # 应用 shutdown 时统一停止
    await stop_shared_client()
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from argus_py.browser.constants import (
    DEFAULT_ACTION_TIMEOUT_MS,
    DEFAULT_NAVIGATION_TIMEOUT_MS,
)
from argus_py.browser.playwright_client import PlaywrightClient
from argus_py.core.constants import DEFAULT_BROWSER, DEFAULT_HEADLESS

logger = logging.getLogger(__name__)

_client: PlaywrightClient | None = None
_lock: threading.Lock = threading.Lock()


def shared_client(
    headless: bool = DEFAULT_HEADLESS,
    browser_type: str = DEFAULT_BROWSER,
    launch_options: dict[str, Any] | None = None,
    action_timeout_ms: int = DEFAULT_ACTION_TIMEOUT_MS,
    navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
) -> PlaywrightClient:
    """获取（或创建）进程级 PlaywrightClient 单例对象。

    **不触发浏览器启动**——只返回 ``PlaywrightClient``，实际的
    ``start()`` 由 ``BrowserSession.start()`` 按需触发。

    首次调用时传入的参数决定了全局配置；后续调用忽略参数直接返回已有实例。
    适用于 ``BrowserSessionFactory`` 等同步上下文。
    """
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is None:
            _client = PlaywrightClient(
                headless=headless,
                browser_type=browser_type,
                launch_options=launch_options or {},
                action_timeout_ms=action_timeout_ms,
                navigation_timeout_ms=navigation_timeout_ms,
            )
    return _client


async def stop_shared_client() -> None:
    """停止进程级 PlaywrightClient 单例并释放全部资源。

    安全可重入：未启动或多重调用不会报错。
    通常在 Worker / 应用 shutdown 阶段调用。

    注：锁内只做指针交换，await client.stop() 在锁外执行，
    避免在 async 上下文阻塞事件循环线程。
    """
    global _client
    _lock.acquire()
    try:
        if _client is None:
            return
        client = _client
        _client = None
    finally:
        _lock.release()
    try:
        await client.stop()
        logger.info("Playwright 单例已停止")
    except Exception:
        logger.warning("停止 Playwright 单例时发生异常", exc_info=True)


async def is_started() -> bool:
    """浏览器单例是否已启动且连接正常。"""
    if _client is None:
        return False
    return _client.is_started
