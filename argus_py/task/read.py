"""任务只读查询服务：CRUD 查询 + 报告/截图路径解析。"""

from __future__ import annotations

import logging
from pathlib import Path

from argus_py.core.constants import KEYWORD_FIELDS, TASK_SEARCH_MIN_LENGTH
from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import TaskError, TaskNotFoundError
from argus_py.core.paths import REPORTS_DIR, SCREENSHOTS_DIR
from argus_py.observability.events import log_event
from argus_py.task.models import Task
from argus_py.task.storage import TaskFileStorage, TaskSQLiteStorage

logger = logging.getLogger(__name__)


def _task_matches_keyword(task: Task, kw: str) -> bool:
    """Python 端 6 字段关键词匹配（FileStorage 回退）。"""
    return any(kw in (getattr(task, f, None) or "").lower() for f in KEYWORD_FIELDS)


class TaskReadService:
    """按 ID 查询、列表查询、分页和计数。"""

    def __init__(
        self,
        storage: TaskFileStorage | TaskSQLiteStorage,
    ) -> None:
        self.storage = storage

    def task_exists(self, task_id: str) -> bool:
        """轻量存在性检查。"""
        return self.storage.exists(task_id)

    def get_task_status(self, task_id: str) -> TaskStatus | None:
        """轻量查询任务当前状态，不加载日志/发现项。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            raw = self.storage.get_task_status(task_id)
            return TaskStatus(raw) if raw else None
        try:
            return self.storage.load(task_id).status
        except TaskNotFoundError:
            return None

    def get_task(self, task_id: str) -> Task:
        """按 ID 获取任务。"""
        if not self.storage.exists(task_id):
            raise TaskNotFoundError(f"Task not found: {task_id}")
        return self.storage.load(task_id)

    def get_latest_task(self, task: Task) -> Task:
        """从存储中读取最新任务快照。

        任务被删除时返回原对象（业务上允许的降级）；DB 损坏、磁盘 I/O 等
        非预期异常向上冒泡，以免上游用过期数据继续决策。
        """
        try:
            return self.get_task(task.task_id)
        except TaskNotFoundError:
            log_event(
                logger, "task.get_latest.fallback", status="error", details={"taskId": task.task_id}
            )
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

        仅支持 SQLite 后端。文件后端没有跨任务索引，O(N) IO 遍历不适合
        仪表盘高频聚合，调用方应切换到 SQLite 后端。
        """
        if isinstance(self.storage, TaskSQLiteStorage):
            return self.storage.count_findings()
        raise RuntimeError("count_findings 仅支持 SQLite 后端。请配置 SQLite 存储后重试。")

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
        if q and len(q) >= TASK_SEARCH_MIN_LENGTH:
            kw = q.lower()
            tasks = [t for t in tasks if _task_matches_keyword(t, kw)]
        return len(tasks)

    def list_task_summaries(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        q: str | None = None,
    ) -> tuple[list[Task], int]:
        """轻量列表查询，返回 (tasks, total_count)，单语句完成。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            return self.storage.list_task_summaries(
                offset=offset,
                limit=limit,
                status=status.value if status else None,
                project_id=project_id,
                q=q,
            )
        tasks = self.list_tasks(status=status, project_id=project_id)
        if q and len(q) >= TASK_SEARCH_MIN_LENGTH:
            kw = q.lower()
            tasks = [t for t in tasks if _task_matches_keyword(t, kw)]
        total = len(tasks)
        if offset:
            tasks = tasks[offset:]
        if limit is not None:
            tasks = tasks[:limit]
        return tasks, total

    # ── 报告路径解析 ──────────────────────────────────────────

    def get_report_path(self, task_id: str) -> str | None:
        """窄查询：只返回 report_path 字段，不加载日志/发现项。"""
        if isinstance(self.storage, TaskSQLiteStorage):
            return self.storage.get_report_path(task_id)
        try:
            task = self.storage.load(task_id)
            return task.report_path
        except TaskNotFoundError:
            return None

    def resolve_report_path_by_id(self, task_id: str) -> Path:
        """窄查询版本：通过 task_id 直接解析并校验 HTML 报告路径。"""
        report_path_str = self.get_report_path(task_id)
        if not report_path_str:
            raise TaskError(f"任务尚未生成报告：{task_id}")
        report_path = Path(report_path_str).expanduser().resolve()
        reports_dir = REPORTS_DIR.resolve()
        if not report_path.is_relative_to(reports_dir):
            raise TaskError(f"报告路径不在允许的报告目录下：{report_path}")
        if not report_path.exists():
            raise TaskError(f"HTML 报告文件不存在：{report_path}")
        return report_path

    def resolve_report_path(self, task: Task) -> Path:
        """解析并校验 HTML 报告路径。"""
        if not task.report_path:
            raise TaskError(f"任务尚未生成报告：{task.task_id}")
        report_path = Path(task.report_path).expanduser().resolve()
        reports_dir = REPORTS_DIR.resolve()
        if not report_path.is_relative_to(reports_dir):
            raise TaskError(f"报告路径不在允许的报告目录下：{report_path}")
        if not report_path.exists():
            raise TaskError(f"HTML 报告文件不存在：{report_path}")
        return report_path

    def resolve_screenshot_path(self, task_id: str, filename: str) -> Path:
        """解析并校验截图文件路径。"""
        screenshot_dir = (SCREENSHOTS_DIR / task_id).resolve()
        screenshot_path = (screenshot_dir / filename).resolve()
        if not screenshot_path.is_relative_to(screenshot_dir):
            raise TaskError("截图路径不合法。")
        if not screenshot_path.exists():
            raise TaskError("截图文件不存在。")
        return screenshot_path
