"""findings 表读写。"""

from __future__ import annotations

from argus_py.infra.db import DbPool
from argus_py.task.models import Finding
from argus_py.task.repositories.mappers import finding_to_row


class FindingRepository:
    """任务发现项存储。"""

    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    def append(self, task_id: str, finding: Finding) -> None:
        """追加单条发现项。"""
        with self._pool.tx() as conn:
            conn.execute(
                "INSERT INTO findings (finding_id, task_id, title, description, severity, finding_type, url, location, screenshot_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                finding_to_row(task_id, finding),
            )

    def count_all(self) -> int:
        """返回所有任务的发现项总数（供仪表盘统计）。"""
        with self._pool.ro_conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM findings").fetchone()
        return row["cnt"] if row else 0
