"""tasks 表 CRUD、列表、计数。"""

from __future__ import annotations

from typing import Any

from argus_py.core.constants import TASK_SEARCH_MIN_LENGTH
from argus_py.core.exceptions import TaskNotFoundError
from argus_py.infra.db import DbPool
from argus_py.task.models import Task
from argus_py.task.repositories.mappers import row_to_task, task_to_row

_KEYWORD_FIELDS = ("name", "goal", "task_id", "start_url", "result_summary", "error_message")


def _sql_keyword_where(q: str) -> tuple[str, list[str]]:
    """返回 (where_clause, params) 用于 6 字段 LIKE 搜索。"""
    pattern = f"%{q}%"
    clause = "(" + " OR ".join(f"{f} LIKE ?" for f in _KEYWORD_FIELDS) + ")"
    return clause, [pattern] * len(_KEYWORD_FIELDS)


class TaskRepository:
    """tasks 表读写。"""

    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    def save(self, task: Task) -> Task:
        with self._pool.tx() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                  task_id, goal, name, start_url, task_type, status, project_id,
                  max_steps, timeout_seconds, capture_screenshots, current_step, parameters_json,
                  created_at, started_at, completed_at, report_path,
                  result_summary, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                  goal = excluded.goal, name = excluded.name,
                  start_url = excluded.start_url, task_type = excluded.task_type,
                  status = excluded.status, project_id = excluded.project_id,
                  max_steps = excluded.max_steps,
                  timeout_seconds = excluded.timeout_seconds,
                  capture_screenshots = excluded.capture_screenshots,
                  current_step = excluded.current_step,
                  parameters_json = excluded.parameters_json,
                  started_at = excluded.started_at,
                  completed_at = excluded.completed_at,
                  report_path = excluded.report_path,
                  result_summary = excluded.result_summary,
                  error_message = excluded.error_message
                """,
                task_to_row(task),
            )
        return task

    def exists(self, task_id: str) -> bool:
        with self._pool.ro_conn() as conn:
            row = conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return row is not None

    def load_task_header(self, task_id: str) -> dict | None:
        """只加载 tasks 表的一行（不含日志/发现项）。"""
        with self._pool.ro_conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return row

    def get_report_path(self, task_id: str) -> str | None:
        """窄查询：只返回 report_path 字段。"""
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT report_path FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return row["report_path"] if row else None

    def get_task_status(self, task_id: str) -> str | None:
        """只查询任务状态字段，不加载日志/发现项。"""
        with self._pool.ro_conn() as conn:
            row = conn.execute("SELECT status FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return row["status"] if row else None

    def load(self, task_id: str) -> Task:
        """读取任务，包含关联的日志和发现项。"""
        with self._pool.ro_conn() as conn:
            task_row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task_row is None:
                raise TaskNotFoundError(f"Task not found: {task_id}")
            log_rows = conn.execute(
                "SELECT * FROM task_logs WHERE task_id = ? ORDER BY step_number, created_at",
                (task_id,),
            ).fetchall()
            finding_rows = conn.execute(
                "SELECT * FROM findings WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return row_to_task(task_row, log_rows, finding_rows)

    def delete(self, task_id: str) -> None:
        """删除任务及关联的日志和发现项。"""
        with self._pool.tx() as conn:
            conn.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM findings WHERE task_id = ?", (task_id,))
            cursor = conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        if cursor.rowcount == 0:
            raise TaskNotFoundError(f"Task not found: {task_id}")

    def update_task(self, task_id: str, **fields: Any) -> None:
        """窄更新：只修改 tasks 表的指定列。"""
        allowed = {
            "status",
            "current_step",
            "started_at",
            "completed_at",
            "report_path",
            "result_summary",
            "error_message",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]
        with self._pool.tx() as conn:
            conn.execute(
                f"UPDATE tasks SET {set_clause} WHERE task_id = ?",
                values,
            )

    def list_tasks(
        self,
        offset: int = 0,
        limit: int | None = None,
        status: str | None = None,
        project_id: str | None = None,
    ) -> list[Task]:
        """列出任务（含完整日志和发现项），支持过滤和分页。"""
        with self._pool.ro_conn() as conn:
            where_clauses: list[str] = []
            params: list[Any] = []
            if status is not None:
                where_clauses.append("status = ?")
                params.append(status)
            if project_id is not None:
                where_clauses.append("project_id = ?")
                params.append(project_id)

            query = "SELECT * FROM tasks"
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
            query += " ORDER BY created_at DESC"
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            elif offset:
                query += " LIMIT -1"
            if offset:
                query += " OFFSET ?"
                params.append(offset)
            task_rows = conn.execute(query, params).fetchall()

            if not task_rows:
                return []

            task_ids = [row["task_id"] for row in task_rows]
            placeholders = ",".join("?" for _ in task_ids)

            log_rows = conn.execute(
                f"SELECT * FROM task_logs WHERE task_id IN ({placeholders}) ORDER BY step_number, created_at",
                task_ids,
            ).fetchall()
            finding_rows = conn.execute(
                f"SELECT * FROM findings WHERE task_id IN ({placeholders}) ORDER BY created_at",
                task_ids,
            ).fetchall()

        logs_by_task: dict[str, list[Any]] = {tid: [] for tid in task_ids}
        for row in log_rows:
            logs_by_task.setdefault(row["task_id"], []).append(row)

        findings_by_task: dict[str, list[Any]] = {tid: [] for tid in task_ids}
        for row in finding_rows:
            findings_by_task.setdefault(row["task_id"], []).append(row)

        return [
            row_to_task(
                task_row,
                logs_by_task.get(task_row["task_id"], []),
                findings_by_task.get(task_row["task_id"], []),
            )
            for task_row in task_rows
        ]

    def count_tasks(
        self,
        status: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> int:
        """返回任务总数，支持按状态、项目和关键词过滤。"""
        with self._pool.ro_conn() as conn:
            query = "SELECT COUNT(*) AS cnt FROM tasks"
            params: list[Any] = []
            where_clauses: list[str] = []
            if status is not None:
                where_clauses.append("status = ?")
                params.append(status)
            if project_id is not None:
                where_clauses.append("project_id = ?")
                params.append(project_id)
            if q:
                if len(q) >= TASK_SEARCH_MIN_LENGTH:
                    clause, kw_params = _sql_keyword_where(q)
                    where_clauses.append(clause)
                    params.extend(kw_params)
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
            row = conn.execute(query, params).fetchone()
        return row["cnt"]

    def list_task_summaries(
        self,
        offset: int = 0,
        limit: int | None = None,
        status: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> tuple[list[Task], int]:
        """轻量列表查询，返回 (tasks, total_count)。

        分两步查询消除 N+1：先查 tasks 列表 + 窗口计数，再批量查 findings
        计数。若合并为一步 LEFT JOIN 则 SQLite 的 COUNT(*) OVER() 会被
        JOIN 膨胀，导致 total_count 不准确。
        """
        with self._pool.ro_conn() as conn:
            where_clauses: list[str] = []
            params: list[Any] = []
            if status is not None:
                where_clauses.append("status = ?")
                params.append(status)
            if project_id is not None:
                where_clauses.append("project_id = ?")
                params.append(project_id)
            if q:
                if len(q) >= TASK_SEARCH_MIN_LENGTH:
                    clause, kw_params = _sql_keyword_where(q)
                    where_clauses.append(clause)
                    params.extend(kw_params)

            query = "SELECT tasks.*, COUNT(*) OVER() AS total_count FROM tasks"
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
            query += " ORDER BY created_at DESC"
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            elif offset:
                query += " LIMIT -1"
            if offset:
                query += " OFFSET ?"
                params.append(offset)

            rows = conn.execute(query, params).fetchall()

            if not rows:
                return [], 0

            task_ids = [r["task_id"] for r in rows]
            placeholders = ",".join("?" for _ in task_ids)
            count_rows = conn.execute(
                f"SELECT task_id, COUNT(*) AS cnt FROM findings "
                f"WHERE task_id IN ({placeholders}) GROUP BY task_id",
                task_ids,
            ).fetchall()
            counts_by_task: dict[str, int] = {r["task_id"]: r["cnt"] for r in count_rows}

        total_count = rows[0]["total_count"]
        tasks = [row_to_task(r, [], []) for r in rows]
        for r, t in zip(rows, tasks, strict=True):
            t.current_step = r["current_step"]
            t.finding_count = counts_by_task.get(r["task_id"], 0)
        return tasks, total_count
