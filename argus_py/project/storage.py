"""项目 SQLite 存储。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from argus_py.core.exceptions import ProjectNotFoundError
from argus_py.infra.db import DEFAULT_DB_PATH, get_db_pool, init_database
from argus_py.project.models import Project


class ProjectSQLiteStorage:
    """基于 SQLite 的项目存储。"""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        init_database(self.db_path)
        self._pool = get_db_pool(self.db_path)

    def exists(self, project_id: str) -> bool:
        """判断项目是否存在。"""
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return row is not None

    def save(self, project: Project) -> Project:
        """保存项目，存在时覆盖。"""
        with self._pool.tx() as conn:
            conn.execute(
                """
                INSERT INTO projects (
                  project_id,
                  name,
                  description,
                  base_url,
                  git_url,
                  auth_state_name,
                  default_max_steps,
                  default_timeout_seconds,
                  default_capture_screenshots,
                  parameters_json,
                  created_at,
                  updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                  name = excluded.name,
                  description = excluded.description,
                  base_url = excluded.base_url,
                  git_url = excluded.git_url,
                  auth_state_name = excluded.auth_state_name,
                  default_max_steps = excluded.default_max_steps,
                  default_timeout_seconds = excluded.default_timeout_seconds,
                  default_capture_screenshots = excluded.default_capture_screenshots,
                  parameters_json = excluded.parameters_json,
                  updated_at = excluded.updated_at
                """,
                self._to_row(project),
            )
        return project

    def load(self, project_id: str) -> Project:
        """按 ID 读取项目。"""
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            raise ProjectNotFoundError(f"Project not found: {project_id}")
        return self._from_row(row)

    def list_projects(self) -> list[Project]:
        """列出项目。"""
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC",
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def delete(self, project_id: str) -> None:
        """删除项目。"""
        with self._pool.tx() as conn:
            cursor = conn.execute(
                "DELETE FROM projects WHERE project_id = ?",
                (project_id,),
            )
        if cursor.rowcount == 0:
            raise ProjectNotFoundError(f"Project not found: {project_id}")

    def find_by_name(self, name: str) -> Project | None:
        """按名称查找项目（精确匹配，区分大小写由 SQLite 排序规则决定）。"""
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE name = ?",
                (name,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def _to_row(self, project: Project) -> tuple[Any, ...]:
        """将项目实体转换为 SQLite 参数。"""
        return (
            project.project_id,
            project.name,
            project.description,
            project.base_url,
            project.git_url,
            project.auth_state_name,
            project.default_max_steps,
            project.default_timeout_seconds,
            1 if project.default_capture_screenshots else 0,
            json.dumps(project.parameters, ensure_ascii=False),
            project.created_at.isoformat(),
            project.updated_at.isoformat(),
        )

    def _from_row(self, row: Any) -> Project:
        """将 SQLite 行转换为项目实体。"""
        return Project.from_dict(
            {
                "project_id": row["project_id"],
                "name": row["name"],
                "description": row["description"],
                "base_url": row["base_url"],
                "git_url": row["git_url"],
                "auth_state_name": row["auth_state_name"],
                "default_max_steps": row["default_max_steps"],
                "default_timeout_seconds": row["default_timeout_seconds"],
                "default_capture_screenshots": bool(row["default_capture_screenshots"]),
                "parameters": json.loads(row["parameters_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
