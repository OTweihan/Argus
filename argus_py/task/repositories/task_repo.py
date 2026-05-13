"""tasks 表 CRUD、列表、计数。"""

from __future__ import annotations

import json
from contextlib import closing
from typing import Any

from argus_py.core.exceptions import TaskError
from argus_py.task.models import Task
from argus_py.task.repositories.mappers import row_to_task, task_to_row


class TaskRepository:
    """tasks 表读写。"""

    def __init__(self, connect):
        self._connect = connect

    def save(self, task: Task) -> Task:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
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
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return row is not None

    def load(self, task_id: str) -> Task:
        """读取任务，包含关联的日志和发现项。"""
        with closing(self._connect()) as connection:
            task_row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise TaskError(f"Task not found: {task_id}")
            log_rows = connection.execute(
                "SELECT * FROM task_logs WHERE task_id = ? ORDER BY step_number, created_at",
                (task_id,),
            ).fetchall()
            finding_rows = connection.execute(
                "SELECT * FROM findings WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return row_to_task(task_row, log_rows, finding_rows)

    def delete(self, task_id: str) -> None:
        """删除任务及关联的日志和发现项。"""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
                connection.execute("DELETE FROM findings WHERE task_id = ?", (task_id,))
                cursor = connection.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        if cursor.rowcount == 0:
            raise TaskError(f"Task not found: {task_id}")

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
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
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
        with closing(self._connect()) as connection:
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
            task_rows = connection.execute(query, params).fetchall()

            if not task_rows:
                return []

            task_ids = [row["task_id"] for row in task_rows]
            placeholders = ",".join("?" for _ in task_ids)

            log_rows = connection.execute(
                f"SELECT * FROM task_logs WHERE task_id IN ({placeholders}) ORDER BY step_number, created_at",
                task_ids,
            ).fetchall()
            finding_rows = connection.execute(
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
        with closing(self._connect()) as connection:
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
                pattern = f"%{q}%"
                where_clauses.append(
                    "(name LIKE ? OR goal LIKE ? OR task_id LIKE ? OR start_url LIKE ? OR result_summary LIKE ? OR error_message LIKE ?)"
                )
                params.extend([pattern] * 6)
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
            row = connection.execute(query, params).fetchone()
        return row["cnt"]

    def list_task_summaries(
        self,
        offset: int = 0,
        limit: int | None = None,
        status: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> list[Task]:
        """轻量列表查询（不含日志和发现项），供列表页使用。"""
        with closing(self._connect()) as connection:
            where_clauses: list[str] = []
            params: list[Any] = []
            if status is not None:
                where_clauses.append("status = ?")
                params.append(status)
            if project_id is not None:
                where_clauses.append("project_id = ?")
                params.append(project_id)
            if q:
                pattern = f"%{q}%"
                where_clauses.append(
                    "(name LIKE ? OR goal LIKE ? OR task_id LIKE ? OR start_url LIKE ? OR result_summary LIKE ? OR error_message LIKE ?)"
                )
                params.extend([pattern] * 6)

            query = """
                SELECT tasks.*,
                  (SELECT COUNT(*) FROM findings WHERE task_id = tasks.task_id) AS finding_count
                FROM tasks
            """
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

            rows = connection.execute(query, params).fetchall()
        tasks = [row_to_task(r, [], []) for r in rows]
        for r, t in zip(rows, tasks):
            t.current_step = r["current_step"]
            t.finding_count = r["finding_count"]
        return tasks
