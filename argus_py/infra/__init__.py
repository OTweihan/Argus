"""基础设施模块。"""

from argus_py.infra.db import DEFAULT_DB_PATH, connect, init_database
from argus_py.infra.events import EventBus, EventSubscription, TaskEvent
from argus_py.infra.queue import EnqueueResult, TaskQueue

__all__ = [
    "DEFAULT_DB_PATH",
    "EnqueueResult",
    "EventBus",
    "EventSubscription",
    "TaskQueue",
    "TaskEvent",
    "TaskWorker",
    "connect",
    "init_database",
]


def __getattr__(name: str):
    """Lazy import for TaskWorker to avoid circular dependency via observability→config→project→infra."""
    if name == "TaskWorker":
        from argus_py.infra.worker import TaskWorker  # noqa: PLC0415

        return TaskWorker
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
