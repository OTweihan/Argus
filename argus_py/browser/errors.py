"""浏览器异常。"""

from __future__ import annotations

from argus_py.core.exceptions import BrowserError


class BrowserNotStartedError(BrowserError):
    """浏览器尚未启动。"""


class BrowserTimeoutError(BrowserError):
    """浏览器操作超时。"""


class ElementNotFoundError(BrowserError):
    """页面元素未找到。"""

    def __init__(self, target: str, strategy: str | None = None) -> None:
        self.target = target
        self.strategy = strategy
        detail = f"{strategy}: {target}" if strategy else target
        super().__init__(f"页面元素未找到：{detail}")


class BrowserActionError(BrowserError):
    """浏览器动作执行失败。"""

    def __init__(self, action: str, message: str, target: str | None = None) -> None:
        self.action = action
        self.target = target
        detail = f"{action}({target})" if target else action
        super().__init__(f"浏览器动作失败：{detail}，原因：{message}")


__all__ = [
    "BrowserError",
    "BrowserNotStartedError",
    "BrowserTimeoutError",
    "ElementNotFoundError",
    "BrowserActionError",
]
