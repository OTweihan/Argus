"""任务子服务的共享基类。

`TaskLifecycleService` 与 `TaskLogService` 都需要：

1. 持有 ``storage``（``TaskFileStorage | TaskSQLiteStorage``）；
2. 接受可选的 ``event_publisher`` 用于推送任务事件；
3. 接受 ``Task`` 对象或 task_id，统一还原为 ``Task``；
4. 在 publisher 存在时通过 ``to_jsonable`` 序列化后转发事件。

把这四点收敛到 ``_StorageEventBase``，避免子服务里 ``_resolve_task`` /
``_publish`` 一字不差地重复两份。`TaskQueryService` 与 `TaskTimelineService`
不需要全部能力，按需各自保留独立实现。
"""

from __future__ import annotations

from typing import Any, Callable

from argus_py.task.models import Task
from argus_py.task.storage import TaskFileStorage, TaskSQLiteStorage
from argus_py.utils.jsonx import to_jsonable

TaskEventPublisher = Callable[[str, str, dict[str, Any]], None]


class _StorageEventBase:
    """任务子服务公共基类：storage + 可选事件发布器 + 通用工具方法。"""

    def __init__(
        self,
        storage: TaskFileStorage | TaskSQLiteStorage,
        event_publisher: TaskEventPublisher | None,
    ) -> None:
        self.storage = storage
        self.event_publisher = event_publisher

    def _resolve_task(self, task: Task | str) -> Task:
        """接受任务对象或任务 ID，统一还原为任务对象。"""
        if isinstance(task, Task):
            return task
        return self.storage.load(task)

    def _publish(self, event_type: str, task: Task, data: dict[str, Any]) -> None:
        """发布任务事件（``event_publisher`` 为 None 时静默忽略）。"""
        if self.event_publisher is None:
            return
        self.event_publisher(event_type, task.task_id, to_jsonable(data))


__all__ = ["TaskEventPublisher", "_StorageEventBase"]
