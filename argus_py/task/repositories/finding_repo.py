"""findings 表写入。"""

from __future__ import annotations

from contextlib import closing

from argus_py.task.models import Finding
from argus_py.task.repositories.mappers import finding_to_row


class FindingRepository:
    """任务发现项存储。"""

    def __init__(self, connect):
        self._connect = connect

    def append(self, task_id: str, finding: Finding) -> None:
        """追加单条发现项。"""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO findings (finding_id, task_id, title, description, severity, finding_type, url, location, screenshot_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    finding_to_row(task_id, finding),
                )
