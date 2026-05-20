"""task_events 表读写。"""

from __future__ import annotations

import json
from typing import Any

from argus_py.infra.db import ConnectFn, with_conn, with_tx
from argus_py.task.repositories.mappers import row_to_event


class EventRepository:
    """时间线事件存储。"""

    def __init__(self, connect: ConnectFn) -> None:
        self._connect = connect

    def append(self, event: Any) -> None:
        """追加单条时间线事件。"""
        from argus_py.task.event import TimelineEvent

        if not isinstance(event, TimelineEvent):
            return
        self.append_batch([event])

    def append_batch(self, events: list[Any]) -> None:
        """批量追加时间线事件，单事务 executemany。"""
        from argus_py.task.event import TimelineEvent

        entries = [e for e in events if isinstance(e, TimelineEvent)]
        if not entries:
            return
        with with_tx(self._connect) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO task_events (event_id, task_id, event_type, phase, step_number, summary, data_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        event.event_id,
                        event.task_id,
                        event.event_type,
                        event.phase,
                        event.step_number,
                        event.summary,
                        json.dumps(event.data, ensure_ascii=False),
                        event.created_at.isoformat(),
                    )
                    for event in entries
                ],
            )

    def load(self, task_id: str) -> list[Any]:
        """按创建时间升序返回任务的时间线事件。"""
        with with_conn(self._connect) as conn:
            rows = conn.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return [row_to_event(r) for r in rows]

    def delete(self, task_id: str) -> None:
        """删除任务的所有时间线事件。"""
        with with_tx(self._connect) as conn:
            conn.execute("DELETE FROM task_events WHERE task_id = ?", (task_id,))
