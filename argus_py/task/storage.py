"""任务存储：文件系统（兼容旧版）和 SQLite（默认，委托 repository 模块）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from argus_py.core.exceptions import TaskNotFoundError
from argus_py.core.paths import DATA_DIR, TEMP_DIR
from argus_py.task.models import Finding, Task, TaskLog
from argus_py.task.repositories.event_repo import EventRepository
from argus_py.task.repositories.finding_repo import FindingRepository
from argus_py.task.repositories.log_repo import LogRepository
from argus_py.task.repositories.task_repo import TaskRepository
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
            raise TaskNotFoundError(f"Task not found: {task_id}")
        path.unlink()


class TaskSQLiteStorage:
    """基于 SQLite 的任务存储（facade，委托 repository 模块）。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        from argus_py.infra.db import connect as _connect_fn
        from argus_py.infra.db import init_database

        self.db_path = Path(db_path) if db_path else DATA_DIR / "argus.db"
        init_database(self.db_path)

        # 把 connect 抽成嵌套 def 以满足 ruff E731；闭包语义与原 lambda 等价：
        # 仓储每次取连接都按构造时的 db_path 解析，避免在仓储构造时就建一个长寿
        # 命的 sqlite3.Connection（连接复用由各 repository 自己控制）。
        resolved_db_path = self.db_path

        def connect():
            return _connect_fn(resolved_db_path)

        self._tasks = TaskRepository(connect)
        self._logs = LogRepository(connect)
        self._findings = FindingRepository(connect)
        self._events = EventRepository(connect)

    # ── 任务 CRUD ───────────────────────────────────────────

    def exists(self, task_id: str) -> bool:
        return self._tasks.exists(task_id)

    def save(self, task: Task) -> Task:
        return self._tasks.save(task)

    def update_task(self, task_id: str, **fields: Any) -> None:
        self._tasks.update_task(task_id, **fields)

    def load(self, task_id: str) -> Task:
        return self._tasks.load(task_id)

    def delete(self, task_id: str) -> None:
        self._tasks.delete(task_id)

    def list_tasks(
        self,
        offset: int = 0,
        limit: int | None = None,
        status: str | None = None,
        project_id: str | None = None,
    ) -> list[Task]:
        return self._tasks.list_tasks(offset, limit, status, project_id)

    def count_tasks(
        self,
        status: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> int:
        return self._tasks.count_tasks(status, project_id, q)

    def list_task_summaries(
        self,
        offset: int = 0,
        limit: int | None = None,
        status: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> tuple[list[Task], int]:
        return self._tasks.list_task_summaries(offset, limit, status, project_id, q)

    # ── 步骤日志 ─────────────────────────────────────────────

    def append_log(self, task_id: str, log: TaskLog) -> None:
        self._logs.append(task_id, log)

    # ── 发现项 ───────────────────────────────────────────────

    def append_finding(self, task_id: str, finding: Finding) -> None:
        self._findings.append(task_id, finding)

    def count_findings(self) -> int:
        """返回 findings 表总记录数（供仪表盘统计）。"""
        return self._findings.count_all()

    # ── 时间线事件 ────────────────────────────────────────────

    def append_event(self, event: Any) -> None:
        self._events.append(event)

    def load_events(self, task_id: str) -> list[Any]:
        return self._events.load(task_id)

    def delete_events(self, task_id: str) -> None:
        self._events.delete(task_id)
