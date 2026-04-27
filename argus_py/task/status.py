"""任务状态流转。"""

from __future__ import annotations

from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import TaskError

VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.TIMEOUT: set(),
    TaskStatus.CANCELLED: set(),
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """判断状态是否允许流转。"""
    return target in VALID_TRANSITIONS.get(current, set())


def assert_transition(current: TaskStatus, target: TaskStatus) -> None:
    """校验状态流转，不合法时抛出异常。"""
    if not can_transition(current, target):
        raise TaskError(f"Invalid task status transition: {current.value} -> {target.value}")
