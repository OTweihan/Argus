"""任务只读查询服务：CRUD 查询 + 报告/截图路径解析。"""

from __future__ import annotations

import logging
from pathlib import Path

from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError, TaskNotFoundError
from argus_py.core.paths import REPORTS_DIR, SCREENSHOTS_DIR
from argus_py.observability.events import log_event
from argus_py.task.models import Task
from argus_py.task.storage import TaskSQLiteStorage

logger = logging.getLogger(__name__)


class TaskReadService:
    """按 ID 查询、列表查询、分页和计数。"""

    def __init__(
        self,
        storage: TaskSQLiteStorage,
    ) -> None:
        self.storage = storage

    def task_exists(self, task_id: str) -> bool:
        """轻量存在性检查。"""
        return self.storage.exists(task_id)

    def get_task_status(self, task_id: str) -> TaskStatus | None:
        """轻量查询任务当前状态，不加载日志/发现项。"""
        raw = self.storage.get_task_status(task_id)
        return TaskStatus(raw) if raw else None

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
        task_type: TaskType | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Task]:
        """列出任务，可按状态、项目和类型过滤，支持分页。"""
        return self.storage.list_tasks(
            offset=offset,
            limit=limit,
            status=status.value if status else None,
            project_id=project_id,
            task_type=task_type.value if task_type else None,
        )

    def count_findings(self) -> int:
        """返回所有任务的发现项总数（仪表盘聚合统计）。"""
        return self.storage.count_findings()

    def count_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        q: str | None = None,
        task_type: TaskType | None = None,
    ) -> int:
        """返回任务总数，支持按状态、项目、类型和关键词过滤。"""
        return self.storage.count_tasks(
            status=status.value if status else None,
            project_id=project_id,
            q=q,
            task_type=task_type.value if task_type else None,
        )

    def list_task_summaries(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        task_type: TaskType | None = None,
        offset: int = 0,
        limit: int | None = None,
        q: str | None = None,
    ) -> tuple[list[Task], int]:
        """轻量列表查询，返回 (tasks, total_count)，单语句完成。"""
        return self.storage.list_task_summaries(
            offset=offset,
            limit=limit,
            status=status.value if status else None,
            project_id=project_id,
            q=q,
            task_type=task_type.value if task_type else None,
        )

    # ── 报告路径解析 ──────────────────────────────────────────

    def get_report_path(self, task_id: str) -> str | None:
        """窄查询：只返回 report_path 字段，不加载日志/发现项。"""
        return self.storage.get_report_path(task_id)

    def resolve_report_path_by_id(self, task_id: str) -> Path:
        """窄查询版本：通过 task_id 直接解析并校验 HTML 报告路径。"""
        report_path_str = self.get_report_path(task_id)
        if not report_path_str:
            raise TaskError(f"任务尚未生成报告：{task_id}")
        return _resolve_report_path(report_path_str)

    def resolve_report_path(self, task: Task) -> Path:
        """解析并校验 HTML 报告路径。"""
        if not task.report_path:
            raise TaskError(f"任务尚未生成报告：{task.task_id}")
        return _resolve_report_path(task.report_path)

    def resolve_screenshot_path(self, task_id: str, filename: str) -> Path:
        """解析并校验截图文件路径。"""
        screenshot_dir = (SCREENSHOTS_DIR / task_id).resolve()
        screenshot_path = (screenshot_dir / filename).resolve()
        if not screenshot_path.is_relative_to(screenshot_dir):
            raise TaskError("截图路径不合法。")
        if not screenshot_path.exists():
            raise TaskError("截图文件不存在。")
        return screenshot_path


def _resolve_report_path(report_path_str: str) -> Path:
    """解析并校验 HTML 报告路径的共享逻辑。"""
    report_path = Path(report_path_str).expanduser().resolve()
    reports_dir = REPORTS_DIR.resolve()
    if not report_path.is_relative_to(reports_dir):
        raise TaskError(f"报告路径不在允许的报告目录下：{report_path}")
    if not report_path.exists():
        raise TaskError(f"HTML 报告文件不存在：{report_path}")
    return report_path
