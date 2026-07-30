"""任务存储：文件系统（兼容旧版）和 SQLite（默认，委托 repository 模块）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from argus_py.core.exceptions import TaskNotFoundError
from argus_py.core.paths import DATA_DIR, TEMP_DIR
from argus_py.task.models import Finding, Task, TaskLog
from argus_py.task.repositories.analysis_repo import AnalysisRunRepository
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
        from argus_py.infra.db import get_db_pool, init_database

        self.db_path = Path(db_path) if db_path else DATA_DIR / "argus.db"
        init_database(self.db_path)
        pool = get_db_pool(self.db_path)
        self._tasks = TaskRepository(pool)
        self._logs = LogRepository(pool)
        self._findings = FindingRepository(pool)
        self._events = EventRepository(pool)
        self._analysis = AnalysisRunRepository(pool)

    # ── 任务 CRUD ───────────────────────────────────────────

    def exists(self, task_id: str) -> bool:
        return self._tasks.exists(task_id)

    def load_task_header(self, task_id: str) -> dict | None:
        return self._tasks.load_task_header(task_id)

    def get_report_path(self, task_id: str) -> str | None:
        return self._tasks.get_report_path(task_id)

    def get_task_status(self, task_id: str) -> str | None:
        return self._tasks.get_task_status(task_id)

    def update_external_job_checkpoint(
        self,
        task_id: str,
        external_job_status: str,
        external_job_last_polled_at: str,
        *,
        expected_status: str | None = None,
    ) -> int:
        """窄更新：只写 external_job 字段，不覆盖 status。"""
        return self._tasks.update_external_job_checkpoint(
            task_id,
            external_job_status,
            external_job_last_polled_at,
            expected_status=expected_status,
        )

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

    def append_log_batch(self, entries: list[tuple[str, TaskLog]]) -> None:
        """批量追加步骤日志（单事务 executemany）。"""
        self._logs.append_batch(entries)

    # ── 发现项 ───────────────────────────────────────────────

    def append_finding(self, task_id: str, finding: Finding) -> None:
        self._findings.append(task_id, finding)

    def count_findings(self) -> int:
        """返回 findings 表总记录数（供仪表盘统计）。"""
        return self._findings.count_all()

    # ── 时间线事件 ────────────────────────────────────────────

    def append_event(self, event: Any) -> None:
        self._events.append(event)

    def append_event_batch(self, events: list[Any]) -> None:
        """批量追加时间线事件（单事务 executemany）。"""
        self._events.append_batch(events)

    def load_events(self, task_id: str) -> list[Any]:
        return self._events.load(task_id)

    def delete_events(self, task_id: str) -> None:
        self._events.delete(task_id)

    # ── 分析执行 ────────────────────────────────────────────

    def create_analysis_run(self, run: Any) -> Any:
        return self._analysis.create(run)

    def get_analysis_run(self, analysis_id: str) -> Any:
        return self._analysis.get(analysis_id)

    def list_analysis_runs(
        self, task_id: str, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[Any], int]:
        return self._analysis.list_by_task(task_id, offset=offset, limit=limit)

    def get_latest_analysis_run(self, task_id: str) -> Any:
        return self._analysis.get_latest(task_id)

    def update_analysis_run_status(self, analysis_id: str, run_status: str, **kw: Any) -> None:
        self._analysis.update_status(analysis_id, run_status, **kw)

    def save_analysis_raw_result(self, analysis_id: str, raw_json: str, digest: str) -> None:
        self._analysis.save_raw_result(analysis_id, raw_json, digest)

    def mark_analysis_failed(
        self, analysis_id: str, failure_code: str, failure_message: str
    ) -> None:
        self._analysis.mark_failed(analysis_id, failure_code, failure_message)

    def complete_analysis_projection(
        self,
        analysis_id: str,
        *,
        completeness: str,
        quality_issues_json: str,
        result_digest: str,
        projection_data: dict[str, Any],
    ) -> None:
        self._analysis.complete_projection(
            analysis_id,
            completeness=completeness,
            quality_issues_json=quality_issues_json,
            result_digest=result_digest,
            projection_data=projection_data,
        )

    def list_analysis_endpoints(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._analysis.list_endpoints(analysis_id, cursor=cursor, limit=limit)

    def list_analysis_call_nodes(
        self,
        analysis_id: str,
        *,
        class_name: str | None = None,
        method_name: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._analysis.list_call_nodes(
            analysis_id,
            class_name=class_name,
            method_name=method_name,
            cursor=cursor,
            limit=limit,
        )

    def list_analysis_call_edges(
        self,
        analysis_id: str,
        *,
        entry_node_id: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._analysis.list_call_edges(
            analysis_id,
            entry_node_id=entry_node_id,
            cursor=cursor,
            limit=limit,
        )

    def list_analysis_execution_flows(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._analysis.list_execution_flows(analysis_id, cursor=cursor, limit=limit)

    def get_analysis_flow_steps(self, flow_id: str) -> list[dict[str, Any]]:
        return self._analysis.get_flow_steps(flow_id)

    def get_analysis_diagnostics(self, analysis_id: str) -> dict[str, Any] | None:
        return self._analysis.get_diagnostics(analysis_id)

    def get_analysis_counts(self, analysis_id: str) -> dict[str, int]:
        return self._analysis.get_counts(analysis_id)
