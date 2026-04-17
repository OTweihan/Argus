"""Task status transitions."""

from argus_py.core.enums import TaskStatus

# Valid state transitions
VALID_TRANSITIONS: dict[TaskStatus, list[TaskStatus]] = {
    TaskStatus.PENDING: [TaskStatus.RUNNING, TaskStatus.CANCELLED],
    TaskStatus.RUNNING: [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED],
    TaskStatus.COMPLETED: [],
    TaskStatus.FAILED: [],
    TaskStatus.TIMEOUT: [],
    TaskStatus.CANCELLED: [],
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """Check if a status transition is valid."""
    return target in VALID_TRANSITIONS.get(current, [])
