"""task_events 表读写。"""

from __future__ import annotations

import json
from contextlib import closing
from typing import Any

from argus_py.task.repositories.mappers import row_to_event


class EventRepository:
    """时间线事件存储。"""

    def __init__(self, connect):
        self._connect = connect

    def append(self, event: Any) -> None:
        """追加单条时间线事件。"""
        from argus_py.task.event import TimelineEvent

        if not isinstance(event, TimelineEvent):
            return
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO task_events (event_id, task_id, event_type, phase, step_number, summary, data_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.task_id,
                        event.event_type,
                        event.phase,
                        event.step_number,
                        event.summary,
                        json.dumps(event.data, ensure_ascii=False),
                        event.created_at.isoformat(),
                    ),
                )

    def load(self, task_id: str) -> list[Any]:
        """按创建时间升序返回任务的时间线事件。"""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return [row_to_event(r) for r in rows]

    def delete(self, task_id: str) -> None:
        """删除任务的所有时间线事件。"""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM task_events WHERE task_id = ?", (task_id,))
