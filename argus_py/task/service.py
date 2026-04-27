"""任务服务骨架。"""

from __future__ import annotations

from datetime import datetime, timezone

from argus_py.core.enums import TaskStatus
from argus_py.task.models import Task
from argus_py.task.status import assert_transition
from argus_py.task.storage import TaskFileStorage


class TaskService:
    """任务创建和状态更新服务。"""

    def __init__(self, storage: TaskFileStorage | None = None) -> None:
        self.storage = storage or TaskFileStorage()

    def create_task(
        self,
        goal: str,
        start_url: str | None = None,
        max_steps: int = 20,
        timeout_seconds: int = 300,
        capture_screenshots: bool = True,
    ) -> Task:
        """创建任务并保存初始快照。"""
        task = Task(
            goal=goal,
            start_url=start_url,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            capture_screenshots=capture_screenshots,
        )
        self.storage.save(task)
        return task

    def update_status(self, task: Task, target: TaskStatus, error_message: str | None = None) -> Task:
        """更新任务状态。"""
        assert_transition(task.status, target)
        now = datetime.now(timezone.utc)
        if target is TaskStatus.RUNNING:
            task.started_at = now
        if target in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED}:
            task.completed_at = now
        task.status = target
        task.error_message = error_message
        self.storage.save(task)
        return task
