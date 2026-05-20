"""任务查询服务（兼容外观层，委托给职责单一的子服务）。

新代码推荐直接使用 ``TaskReadService`` / ``TraceReadService`` /
``DebugBundleBuilder``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from argus_py.core.enums import TaskStatus
from argus_py.observability.debug_bundle import DebugBundleBuilder
from argus_py.observability.trace_reader import TraceReadService
from argus_py.task.models import Task
from argus_py.task.read import TaskReadService
from argus_py.task.storage import TaskFileStorage, TaskSQLiteStorage


class TaskQueryService:
    """兼容外观：保留原有全部公开方法签名，内部委托给单一职责子服务。

    新代码推荐直接使用 ``TaskReadService`` / ``TraceReadService`` /
    ``DebugBundleBuilder``。
    """

    def __init__(
        self,
        storage: TaskFileStorage | TaskSQLiteStorage,
    ) -> None:
        self.reader = TaskReadService(storage)
        self.trace_reader = TraceReadService()
        self.debug_builder = DebugBundleBuilder()

    # ── CRUD 查询（委托 reader） ──

    def task_exists(self, task_id: str) -> bool:
        return self.reader.task_exists(task_id)

    def get_task_status(self, task_id: str) -> TaskStatus | None:
        return self.reader.get_task_status(task_id)

    def get_task(self, task_id: str) -> Task:
        return self.reader.get_task(task_id)

    def get_latest_task(self, task: Task) -> Task:
        return self.reader.get_latest_task(task)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Task]:
        return self.reader.list_tasks(
            status=status, project_id=project_id, offset=offset, limit=limit
        )

    def count_findings(self) -> int:
        return self.reader.count_findings()

    def count_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> int:
        return self.reader.count_tasks(status=status, project_id=project_id, q=q)

    def list_task_summaries(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        q: str | None = None,
    ) -> tuple[list[Task], int]:
        return self.reader.list_task_summaries(
            status=status, project_id=project_id, offset=offset, limit=limit, q=q
        )

    def get_report_path(self, task_id: str) -> str | None:
        return self.reader.get_report_path(task_id)

    def resolve_report_path_by_id(self, task_id: str) -> Path:
        return self.reader.resolve_report_path_by_id(task_id)

    def resolve_report_path(self, task: Task) -> Path:
        return self.reader.resolve_report_path(task)

    def resolve_screenshot_path(self, task_id: str, filename: str) -> Path:
        return self.reader.resolve_screenshot_path(task_id, filename)

    # ── LLM 追踪（委托 trace_reader） ──

    def list_llm_traces(
        self,
        task_id: str,
        skip: int = 0,
        limit: int = 50,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.trace_reader.list_llm_traces(task_id, skip=skip, limit=limit, trace_id=trace_id)

    def get_llm_trace_detail(self, task_id: str, trace_id: str) -> dict[str, Any] | None:
        return self.trace_reader.get_llm_trace_detail(task_id, trace_id)

    # ── 调试包（委托 debug_builder） ──

    def build_debug_bundle(
        self, task_id: str, task: Task, events: list[dict[str, Any]] | None = None
    ) -> str:
        return self.debug_builder.build(task_id, task, events=events)
