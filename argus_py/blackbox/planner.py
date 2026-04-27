"""黑盒任务规划器。"""

from __future__ import annotations

from argus_py.blackbox.models import ActionSequence, ActionStep, BlackboxTaskInput
from argus_py.core.enums import ActionType


class BlackboxPlanner:
    """黑盒动作规划边界。"""

    async def plan_initial(self, task_input: BlackboxTaskInput) -> ActionSequence:
        """生成初始动作序列。MVP 骨架先提供确定性首步。"""
        steps = [ActionStep(action=ActionType.GOTO, url=task_input.start_url, reason="打开起始 URL")]
        if task_input.capture_screenshots:
            steps.append(ActionStep(action=ActionType.SCREENSHOT, reason="记录初始页面证据"))
        return ActionSequence(steps=steps, summary="初始骨架规划，仅包含打开页面和截图。")
