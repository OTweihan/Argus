"""findings 表读写。"""

from __future__ import annotations

import base64
import json
from typing import Any

from argus_py.infra.db import DbPool
from argus_py.task.models import Finding
from argus_py.task.repositories.mappers import finding_to_row, row_to_finding


class FindingRepository:
    """任务发现项存储。"""

    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    def append(self, task_id: str, finding: Finding) -> None:
        """追加单条发现项。"""
        with self._pool.tx() as conn:
            conn.execute(
                "INSERT INTO findings (finding_id, task_id, title, description, "
                "severity, finding_type, url, location, screenshot_path, created_at, "
                "rule_id, rule_category, confidence, fingerprint, snippet, analysis_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                finding_to_row(task_id, finding),
            )

    def delete_by_analysis_id(self, analysis_id: str) -> None:
        """删除指定分析执行的所有发现项（幂等清理，用于重新执行时避免累积）。"""
        with self._pool.tx() as conn:
            conn.execute(
                "DELETE FROM findings WHERE analysis_id = ?",
                (analysis_id,),
            )

    def count_all(self) -> int:
        """返回所有任务的发现项总数（供仪表盘统计）。"""
        with self._pool.ro_conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM findings").fetchone()
        return row["cnt"] if row else 0

    def list_by_analysis_id(
        self,
        analysis_id: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[Finding], str | None, int | None, bool]:
        """按 analysis_id 分页查询发现项（游标分页，按 created_at DESC）。"""
        params: list[Any] = [analysis_id]

        with self._pool.ro_conn() as conn:
            # total
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM findings WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
            total: int | None = row["cnt"] if row else 0

            limit = min(limit, 200)

            sql = "SELECT * FROM findings WHERE analysis_id = ?"
            if cursor:
                try:
                    decoded = json.loads(base64.urlsafe_b64decode(cursor).decode())
                    cursor_keys = decoded["k"]  # [created_at, finding_id]
                    sql += " AND (created_at < ? OR (created_at = ? AND finding_id > ?))"
                    params = [
                        analysis_id,
                        cursor_keys[0],
                        cursor_keys[0],
                        cursor_keys[1],
                    ]
                except Exception:
                    cursor = None

            sql += " ORDER BY created_at DESC, finding_id ASC LIMIT ?"
            params_with_limit = list(params) + [limit + 1]
            rows = conn.execute(sql, params_with_limit).fetchall()

        items = [row_to_finding(r) for r in rows]
        has_more = len(items) > limit
        if has_more:
            items.pop()

        next_cursor: str | None = None
        if has_more and items:
            last = rows[limit - 1] if len(rows) > limit else rows[-1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps({"k": [last["created_at"], last["finding_id"]]}).encode()
            ).decode()

        return items, next_cursor, total, has_more
