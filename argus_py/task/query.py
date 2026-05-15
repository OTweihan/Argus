"""任务查询服务。"""

from __future__ import annotations

from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import TaskNotFoundError
from argus_py.task.models import Task
from argus_py.task.storage import TaskFileStorage, TaskSQLiteStorage


class TaskQueryService:
    """按 ID 查询、列表查询、分页和计数。"""

    def __init__(
        self,
        storage: TaskFileStorage | TaskSQLiteStorage,
    ) -> None:
        self.storage = storage

    def get_task(self, task_id: str) -> Task:
        """按 ID 获取任务。"""
        if not self.storage.exists(task_id):
            raise TaskNotFoundError(f"Task not found: {task_id}")
        return self.storage.load(task_id)

    def get_latest_task(self, task: Task) -> Task:
        """从存储中读取最新任务快照，失败时返回原对象。"""
        try:
            return self.get_task(task.task_id)
        except Exception:
            return task

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Task]:
        """列出任务，可按状态和项目过滤，支持分页。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            return self.storage.list_tasks(
                offset=offset,
                limit=limit,
                status=status.value if status else None,
                project_id=project_id,
            )
        has_filter = status is not None or project_id is not None
        if has_filter:
            tasks = self.storage.list_tasks()
            if status is not None:
                tasks = [task for task in tasks if task.status is status]
            if project_id is not None:
                tasks = [task for task in tasks if task.project_id == project_id]
            if offset:
                tasks = tasks[offset:]
            if limit is not None:
                tasks = tasks[:limit]
            return tasks
        return self.storage.list_tasks(offset=offset, limit=limit)

    def count_findings(self) -> int:
        """返回所有任务的发现项总数（仪表盘聚合统计）。

        非 SQLite 后端没有跨任务索引，遍历任务文件聚合 ``len(findings)`` 仍能给出正确值。
        """
        if isinstance(self.storage, TaskSQLiteStorage):
            return self.storage.count_findings()
        return sum(len(task.findings or []) for task in self.storage.list_tasks())

    def count_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> int:
        """返回任务总数，支持按状态、项目和关键词过滤。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            return self.storage.count_tasks(
                status=status.value if status else None,
                project_id=project_id,
                q=q,
            )
        if status is None and project_id is None and q is None:
            return self.storage.count_tasks()
        tasks = self.list_tasks(status=status, project_id=project_id)
        if q:
            kw = q.lower()
            tasks = [
                t
                for t in tasks
                if kw in (t.name or "").lower()
                or kw in (t.goal or "").lower()
                or kw in (t.task_id or "").lower()
                or kw in (t.start_url or "").lower()
                or kw in (t.result_summary or "").lower()
                or kw in (t.error_message or "").lower()
            ]
        return len(tasks)

    def list_task_summaries(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        q: str | None = None,
    ) -> list[Task]:
        """轻量列表查询（不含日志和发现项），供列表页使用。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            return self.storage.list_task_summaries(
                offset=offset,
                limit=limit,
                status=status.value if status else None,
                project_id=project_id,
                q=q,
            )
        tasks = self.list_tasks(status=status, project_id=project_id)
        if q:
            kw = q.lower()
            tasks = [
                t
                for t in tasks
                if kw in (t.name or "").lower()
                or kw in (t.goal or "").lower()
                or kw in (t.task_id or "").lower()
                or kw in (t.start_url or "").lower()
                or kw in (t.result_summary or "").lower()
                or kw in (t.error_message or "").lower()
            ]
        if offset:
            tasks = tasks[offset:]
        if limit is not None:
            tasks = tasks[:limit]
        return tasks
