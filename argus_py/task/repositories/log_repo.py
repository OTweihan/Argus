"""task_logs 表写入。"""

from __future__ import annotations

from argus_py.infra.db import ConnectFn, with_tx
from argus_py.task.models import TaskLog
from argus_py.task.repositories.mappers import log_to_row


class LogRepository:
    """任务步骤日志存储。"""

    def __init__(self, connect: ConnectFn) -> None:
        self._connect = connect

    def append(self, task_id: str, log: TaskLog) -> None:
        """追加单条步骤日志。"""
        with with_tx(self._connect) as conn:
            conn.execute(
                "INSERT INTO task_logs (task_log_id, task_id, step_number, action, result, params_json, url_before, url_after, screenshot_path, message, error, error_code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                log_to_row(task_id, log),
            )
            conn.execute(
                "UPDATE tasks SET current_step = current_step + 1 WHERE task_id = ?",
                (task_id,),
            )
