"""任务存储：文件系统（兼容旧版）和 SQLite（默认）。"""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any

from argus_py.core.exceptions import TaskError
from argus_py.core.paths import DATA_DIR, TEMP_DIR
from argus_py.task.models import Finding, Task, TaskLog
from argus_py.utils.jsonx import read_json, to_jsonable, write_json


class TaskFileStorage:
    """基于文件系统的任务存储，供 MVP 阶段替代数据库。"""

    def __init__(self, base_dir: str | Path = TEMP_DIR / "tasks") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def task_path(self, task_id: str) -> Path:
        """返回任务 JSON 路径。"""
        return self.base_dir / f"{task_id}.json"

    def exists(self, task_id: str) -> bool:
        """判断任务快照是否存在。"""
        return self.task_path(task_id).exists()

    def save(self, task: Task) -> Path:
        """保存任务快照。"""
        return write_json(self.task_path(task.task_id), to_jsonable(task))

    def load_raw(self, task_id: str) -> dict:
        """读取任务原始 JSON 数据。"""
        return read_json(self.task_path(task_id))

    def load(self, task_id: str) -> Task:
        """读取并还原任务实体。"""
        return Task.from_dict(self.load_raw(task_id))

    def list_ids(self) -> list[str]:
        """列出已保存任务 ID（按文件名字母序，即大致按创建时间排序）。"""
        return sorted(path.stem for path in self.base_dir.glob("*.json"))

    def list_tasks(self, offset: int = 0, limit: int | None = None) -> list[Task]:
        """列出已保存任务，支持分页以减轻磁盘 I/O。"""
        ids = self.list_ids()
        ids.reverse()
        if offset:
            ids = ids[offset:]
        if limit is not None:
            ids = ids[:limit]
        tasks = [self.load(task_id) for task_id in ids]
        return sorted(tasks, key=lambda item: item.created_at, reverse=True)

    def count_tasks(self) -> int:
        """快速返回任务总数（仅列文件名，不反序列化）。"""
        return len(self.list_ids())

    def delete(self, task_id: str) -> None:
        """删除任务快照。"""
        path = self.task_path(task_id)
        if not path.exists():
            raise TaskError(f"Task not found: {task_id}")
        path.unlink()


class TaskSQLiteStorage:
    """基于 SQLite 的任务存储。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        from argus_py.infra.db import connect as _connect_fn
        from argus_py.infra.db import init_database

        self._connect = lambda: (
            _connect_fn(db_path) if db_path else _connect_fn(DATA_DIR / "argus.db")
        )
        self.db_path = Path(db_path) if db_path else DATA_DIR / "argus.db"
        init_database(self.db_path)

    def exists(self, task_id: str) -> bool:
        """判断任务是否存在。"""
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return row is not None

    def save(self, task: Task) -> Task:
        """保存任务（仅写入 tasks 表；日志和发现项通过 append_log / append_finding 独立写入）。"""
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
                      goal = excluded.goal,
                      name = excluded.name,
                      start_url = excluded.start_url,
                      task_type = excluded.task_type,
                      status = excluded.status,
                      project_id = excluded.project_id,
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
                    self._task_to_row(task),
                )
        return task

    def update_task(self, task_id: str, **fields: Any) -> None:
        """窄更新：只修改 tasks 表的指定列，不触及 task_logs/findings。"""
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

    def append_log(self, task_id: str, log: TaskLog) -> None:
        """追加单条步骤日志。"""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO task_logs (task_log_id, task_id, step_number, action, result, params_json, url_before, url_after, screenshot_path, message, error, error_code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._log_to_row(task_id, log),
                )
                connection.execute(
                    "UPDATE tasks SET current_step = current_step + 1 WHERE task_id = ?",
                    (task_id,),
                )

    def append_finding(self, task_id: str, finding: Finding) -> None:
        """追加单条发现项。"""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO findings (finding_id, task_id, title, description, severity, finding_type, url, location, screenshot_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._finding_to_row(task_id, finding),
                )

    def load(self, task_id: str) -> Task:
        """按 ID 读取任务，包含关联的日志和发现项。"""
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
        return self._row_to_task(task_row, log_rows, finding_rows)

    def delete(self, task_id: str) -> None:
        """删除任务及关联的日志和发现项。"""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
                connection.execute("DELETE FROM findings WHERE task_id = ?", (task_id,))
                cursor = connection.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        if cursor.rowcount == 0:
            raise TaskError(f"Task not found: {task_id}")

    def list_tasks(
        self,
        offset: int = 0,
        limit: int | None = None,
        status: str | None = None,
        project_id: str | None = None,
    ) -> list[Task]:
        """列出已保存任务（含完整日志和发现项），支持过滤和分页。"""
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
            self._row_to_task(
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
        """轻量列表查询（不含日志和发现项），供任务列表页使用。"""
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
        tasks = [self._row_to_task(r, [], []) for r in rows]
        for r, t in zip(rows, tasks):
            t.current_step = r["current_step"]
            t.finding_count = r["finding_count"]
        return tasks

    def _task_to_row(self, task: Task) -> tuple[Any, ...]:
        """将 Task 实体转换为 SQLite INSERT 参数。"""
        return (
            task.task_id,
            task.goal,
            task.name,
            task.start_url,
            task.task_type.value,
            task.status.value,
            task.project_id,
            task.max_steps,
            task.timeout_seconds,
            1 if task.capture_screenshots else 0,
            task.current_step,
            json.dumps(task.parameters, ensure_ascii=False),
            task.created_at.isoformat(),
            task.started_at.isoformat() if task.started_at else None,
            task.completed_at.isoformat() if task.completed_at else None,
            task.report_path,
            task.result_summary,
            task.error_message,
        )

    def _log_to_row(self, task_id: str, log: TaskLog) -> tuple[Any, ...]:
        """将 TaskLog 实体转换为 SQLite INSERT 参数。"""
        return (
            log.task_log_id,
            task_id,
            log.step_number,
            log.action,
            log.result.value,
            json.dumps(log.params, ensure_ascii=False),
            log.url_before,
            log.url_after,
            log.screenshot_path,
            log.message,
            log.error,
            log.error_code,
            log.created_at.isoformat(),
        )

    def _finding_to_row(self, task_id: str, finding: Finding) -> tuple[Any, ...]:
        """将 Finding 实体转换为 SQLite INSERT 参数。"""
        return (
            finding.finding_id,
            task_id,
            finding.title,
            finding.description,
            finding.severity.value,
            finding.finding_type.value,
            finding.url,
            finding.location,
            finding.screenshot_path,
            finding.created_at.isoformat(),
        )

    def _row_to_task(
        self,
        task_row: Any,
        log_rows: list[Any],
        finding_rows: list[Any],
    ) -> Task:
        """将 SQLite 行还原为 Task 实体。"""
        from argus_py.core.enums import TaskStatus, TaskType
        from argus_py.task.models import _parse_datetime, utc_now

        return Task(
            task_id=task_row["task_id"],
            goal=task_row["goal"],
            name=task_row["name"],
            start_url=task_row["start_url"],
            task_type=TaskType(task_row["task_type"]),
            status=TaskStatus(task_row["status"]),
            project_id=task_row["project_id"],
            max_steps=task_row["max_steps"],
            timeout_seconds=task_row["timeout_seconds"],
            capture_screenshots=bool(task_row["capture_screenshots"]),
            parameters=json.loads(task_row["parameters_json"] or "{}"),
            logs=[self._row_to_log(r) for r in log_rows],
            findings=[self._row_to_finding(r) for r in finding_rows],
            created_at=_parse_datetime(task_row["created_at"]) or utc_now(),
            started_at=_parse_datetime(task_row["started_at"]),
            completed_at=_parse_datetime(task_row["completed_at"]),
            report_path=task_row["report_path"],
            result_summary=task_row["result_summary"],
            error_message=task_row["error_message"],
        )

    def _row_to_log(self, row: Any) -> TaskLog:
        """将 SQLite 行还原为 TaskLog 实体。"""
        from argus_py.core.enums import StepResult
        from argus_py.task.models import _parse_datetime, utc_now

        return TaskLog(
            task_log_id=row["task_log_id"],
            step_number=row["step_number"],
            action=row["action"],
            result=StepResult(row["result"]),
            params=json.loads(row["params_json"] or "{}"),
            url_before=row["url_before"],
            url_after=row["url_after"],
            screenshot_path=row["screenshot_path"],
            message=row["message"],
            error=row["error"],
            error_code=row["error_code"],
            created_at=_parse_datetime(row["created_at"]) or utc_now(),
        )

    def _row_to_finding(self, row: Any) -> Finding:
        """将 SQLite 行还原为 Finding 实体。"""
        from argus_py.core.enums import FindingSeverity, FindingType
        from argus_py.task.models import _parse_datetime, utc_now

        return Finding(
            finding_id=row["finding_id"],
            title=row["title"],
            description=row["description"],
            severity=FindingSeverity(row["severity"]),
            finding_type=FindingType(row["finding_type"]),
            url=row["url"],
            location=row["location"],
            screenshot_path=row["screenshot_path"],
            created_at=_parse_datetime(row["created_at"]) or utc_now(),
        )
