"""黑盒任务模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from argus_py.core.constants import DEFAULT_MAX_STEPS, DEFAULT_TASK_TIMEOUT_S
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionStep":
        """从 LLM JSON 对象还原浏览器动作。"""
        raw_action = str(data["action"]).lower()
        return cls(
            action=ActionType(raw_action),
            reason=str(data.get("reason") or ""),
            selector=data.get("selector"),
            url=data.get("url"),
            text=data.get("text"),
            key=data.get("key"),
            wait_ms=data.get("wait_ms"),
            params=dict(data.get("params") or {}),
        )


@dataclass
class ActionSequence:
    """动作序列。"""

    steps: list[ActionStep] = field(default_factory=list)
    summary: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionSequence":
        """从 LLM JSON 对象还原动作序列。"""
        return cls(
            steps=[ActionStep.from_dict(item) for item in data.get("steps", [])],
            summary=str(data.get("summary") or ""),
        )


@dataclass
class BlackboxTaskInput:
    """黑盒测试输入。"""

    goal: str
    start_url: str
    max_steps: int = DEFAULT_MAX_STEPS
    timeout_seconds: int = DEFAULT_TASK_TIMEOUT_S
    capture_screenshots: bool = True
    prompt_extensions: dict[str, str] = field(default_factory=dict)
