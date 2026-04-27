"""任务执行入口骨架。"""

from __future__ import annotations

from argus_py.core.exceptions import TaskError
from argus_py.task.models import Task


class TaskRunner:
    """单进程任务执行器。"""

    async def run(self, task: Task) -> Task:
        """执行任务。完整黑盒闭环将在 T005/T007 实现。"""
        raise TaskError("TaskRunner.run() 尚未实现，后续在 T005/T007 接入黑盒 Agent。")
