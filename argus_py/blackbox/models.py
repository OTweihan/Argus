"""黑盒任务模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from argus_py.core.enums import ActionType


@dataclass
class ActionStep:
    """规划器输出的一步浏览器动作。"""

    action: ActionType
    reason: str = ""
    selector: str | None = None
    url: str | None = None
    text: str | None = None
    key: str | None = None
    wait_ms: int | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionSequence:
    """动作序列。"""

    steps: list[ActionStep] = field(default_factory=list)
    summary: str = ""


@dataclass
class BlackboxTaskInput:
    """黑盒测试输入。"""

    goal: str
    start_url: str
    max_steps: int = 20
    timeout_seconds: int = 300
    capture_screenshots: bool = True
