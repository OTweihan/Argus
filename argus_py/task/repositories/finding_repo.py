"""findings 表读写。"""

from __future__ import annotations

from argus_py.infra.db import DbPool
from argus_py.task.models import Finding
from argus_py.task.repositories.mappers import finding_to_row, row_to_finding
from argus_py.task.repositories.pagination import cursor_paginate


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

    def insert_batch(self, task_id: str, findings: list[Finding]) -> None:
        """同事务批量写入一批发现项（避免逐条开事务的 N+1 写放大）。

        白盒分析 findings 可能达数百条，逐条 ``append`` 会开等量写事务；
        这里改为单事务 ``executemany``，行元组已在内存中（``task.findings``），
        无需再分片。
        """
        if not findings:
            return
        with self._pool.tx() as conn:
            conn.executemany(
                "INSERT INTO findings (finding_id, task_id, title, description, "
                "severity, finding_type, url, location, screenshot_path, created_at, "
                "rule_id, rule_category, confidence, fingerprint, snippet, analysis_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (finding_to_row(task_id, f) for f in findings),
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
        """按 analysis_id 分页查询发现项（游标分页，按 created_at DESC）。

        与 O-10 修正后的 ``_paginated_query`` 共用同一 keyset 实现
        （``repositories/pagination.py``）：仅在无有效游标（首页或非法游标
        回退首页）时计算 total；后续 cursor 页返回 None，由客户端复用首页
        total，避免每页重复全表/索引 COUNT。
        """
        with self._pool.ro_conn() as conn:
            rows, next_cursor, total, has_more = cursor_paginate(
                conn,
                "findings",
                order="created_at DESC, finding_id ASC",
                where="analysis_id = ?",
                params=[analysis_id],
                cursor=cursor,
                limit=limit,
            )
        return [row_to_finding(r) for r in rows], next_cursor, total, has_more

    def list_all_by_analysis_id(self, analysis_id: str) -> list[Finding]:
        """返回分析的全部发现项（无 200 行钳制，关联匹配引擎用）。

        与 ``list_by_analysis_id`` 的分页钳制（``limit=min(limit,200)``）不同，
        关联引擎需要全量发现项生成 FindingEvidence，此前被静默截断为前 200 行。
        """
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM findings WHERE analysis_id = ? "
                "ORDER BY created_at DESC, finding_id ASC",
                (analysis_id,),
            ).fetchall()
        return [row_to_finding(r) for r in rows]
