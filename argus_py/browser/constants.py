"""Browser 子树独占的运行时默认值。

放在子模块而不是 ``argus_py.core.constants`` 是为了让 browser 相关参数的
"声明—使用"靠在一起：未来要再调超时阈值、加新 page lifecycle 钩子时，
不必跨包翻找。``argus_py.core.constants`` 只保留跨模块共享的常量
（项目名 / LLM 默认值 / 任务上限等）。
"""

from __future__ import annotations

from argus_py.core.paths import SCREENSHOTS_DIR

DEFAULT_SCREENSHOTS_DIR: str = str(SCREENSHOTS_DIR)

DEFAULT_ACTION_TIMEOUT_MS: int = 10000
DEFAULT_NAVIGATION_TIMEOUT_MS: int = 30000
DEFAULT_PAGE_READY_TIMEOUT_MS: int = 8000
DEFAULT_PAGE_SETTLE_MS: int = 500
