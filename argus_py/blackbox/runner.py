"""黑盒 Agent 执行器骨架。"""

from __future__ import annotations

from argus_py.blackbox.models import BlackboxTaskInput
from argus_py.core.exceptions import TaskError
from argus_py.task.models import Task


class BlackboxRunner:
    """串联规划、浏览器和评估的执行边界。"""

    async def run(self, task: Task | BlackboxTaskInput) -> Task | BlackboxTaskInput:
        """完整动作循环将在 T005 实现。"""
        raise TaskError("BlackboxRunner.run() 尚未实现，当前仅完成项目骨架。")
