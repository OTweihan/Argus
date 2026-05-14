"""任务执行时间线事件。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from argus_py.core.ids import generate_id
from argus_py.task.storage import TaskSQLiteStorage

TaskEventPublisher = Callable[[str, str, dict[str, Any]], None]

# ── 时间线阶段与事件类型 ──────────────────────────────────

TIMELINE_PHASES = {
    "task": "任务生命周期",
    "browser": "浏览器操作",
    "planner": "Planner LLM 调用",
    "executor": "动作执行",
    "evaluator": "Evaluator LLM 调用",
    "report": "报告生成",
}

TIMELINE_EVENT_TYPES = [
    "start",
    "open_url",
    "snapshot",
    "planner_start",
    "planner_result",
    "action",
    "evaluator_start",
    "evaluator_result",
    "report",
    "complete",
    "fail",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TimelineEvent:
    """执行时间线事件。"""

    event_id: str = ""
    task_id: str = ""
    event_type: str = ""  # 见 TIMELINE_EVENT_TYPES
    phase: str = ""  # 见 TIMELINE_PHASES key
    step_number: int = 0
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        """JSON 序列化（用于 API 输出）。"""
        return {
            "eventId": self.event_id,
            "taskId": self.task_id,
            "eventType": self.event_type,
            "phase": self.phase,
            "stepNumber": self.step_number,
            "summary": self.summary,
            "data": self.data,
            "createdAt": self.created_at.isoformat(),
        }


class TaskTimelineService:
    """时间线事件管理：持久化 + 实时发布。"""

    def __init__(
        self,
        storage: TaskSQLiteStorage,
        event_publisher: TaskEventPublisher | None = None,
    ) -> None:
        self.storage = storage
        self.event_publisher = event_publisher

    def emit(
        self,
        task_id: str,
        event_type: str,
        phase: str,
        step_number: int = 0,
        summary: str = "",
        data: dict[str, Any] | None = None,
    ) -> TimelineEvent:
        """创建、持久化并发布一条时间线事件。"""
        event = TimelineEvent(
            event_id=generate_id("evt"),
            task_id=task_id,
            event_type=event_type,
            phase=phase,
            step_number=step_number,
            summary=summary,
            data=data or {},
        )
        self.storage.append_event(event)
        if self.event_publisher is not None:
            self.event_publisher(
                f"task.timeline.{phase}",
                task_id,
                event.to_dict(),
            )
        return event

    def list_by_task(self, task_id: str) -> list[TimelineEvent]:
        """按创建时间升序返回任务的时间线事件。"""
        return self.storage.load_events(task_id)

    def delete_by_task(self, task_id: str) -> None:
        """删除任务的所有时间线事件。"""
        self.storage.delete_events(task_id)


class _NullTimelineService:
    """``TaskTimelineService`` 的 Null Object：所有方法都是空操作。

    用于 ``TaskService`` 在底层 storage 不是 SQLite（仅 ``TaskFileStorage``）
    时占位，使 facade 不必每次都 ``if self.timeline is None: return``。
    """

    def emit(
        self,
        task_id: str,  # noqa: ARG002 - Null Object 接口对齐
        event_type: str,  # noqa: ARG002
        phase: str,  # noqa: ARG002
        step_number: int = 0,  # noqa: ARG002
        summary: str = "",  # noqa: ARG002
        data: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> None:
        return None

    def list_by_task(self, task_id: str) -> list[TimelineEvent]:  # noqa: ARG002
        return []

    def delete_by_task(self, task_id: str) -> None:  # noqa: ARG002
        return None
