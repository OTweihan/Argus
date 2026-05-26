"""task_logs 表写入。"""

from __future__ import annotations

from argus_py.infra.db import DbPool
from argus_py.task.models import TaskLog
from argus_py.task.repositories.mappers import log_to_row


class LogRepository:
    """任务步骤日志存储。"""

    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    def append(self, task_id: str, log: TaskLog) -> None:
        """追加单条步骤日志。"""
        self.append_batch([(task_id, log)])

    def append_batch(self, entries: list[tuple[str, TaskLog]]) -> None:
        """批量追加步骤日志，单事务 executemany。"""
        if not entries:
            return
        with self._pool.tx() as conn:
            conn.executemany(
                "INSERT INTO task_logs (task_log_id, task_id, step_number, action, result, params_json, url_before, url_after, screenshot_path, message, error, error_code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [log_to_row(task_id, log) for task_id, log in entries],
            )
            # 按 (task_id, step_number) 去重，避免同一步产生冗余 UPDATE
            unique_updates = {(task_id, log.step_number) for task_id, log in entries}
            conn.executemany(
                "UPDATE tasks SET current_step = max(current_step, ?) WHERE task_id = ?",
                [(step, tid) for tid, step in unique_updates],
            )
