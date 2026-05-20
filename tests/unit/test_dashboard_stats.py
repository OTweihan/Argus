"""验证 dashboard 复用 list_task_summaries 的窗口函数 total。

同时确保 tasks_total 与跨页总数一致（不被 limit 截断）。
"""

from __future__ import annotations

from argus_py.config.model_storage import ModelConfigSQLiteStorage
from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.infra.queue import TaskQueue
from argus_py.project.service import ProjectService
from argus_py.project.storage import ProjectSQLiteStorage
from argus_py.task.application import TaskApplicationService
from argus_py.task.service import TaskService
from argus_py.task.storage import TaskSQLiteStorage


def _make_stack(tmp_path) -> TaskApplicationService:
    # dashboard 需要 count_findings，仅 SQLite 后端支持；TaskFileStorage 不行。
    task_service = TaskService(TaskSQLiteStorage(tmp_path / "argus.db"))
    project_service = ProjectService(
        ProjectSQLiteStorage(tmp_path / "argus.db"),
        task_read_service=task_service.reader,
    )
    return TaskApplicationService(
        task_service=task_service,
        queue=TaskQueue(),
        project_service=project_service,
        model_config_service=ModelConfigService(ModelConfigSQLiteStorage(tmp_path / "models.db")),
    )


def test_dashboard_total_matches_full_table_count(tmp_path) -> None:
    """tasks_total 必须是全表数量，不受 recent_limit 影响。"""
    app = _make_stack(tmp_path)
    for i in range(7):
        app._task.create_task(goal=f"goal {i}", task_type=TaskType.BLACKBOX)

    stats = app.get_dashboard_stats(recent_limit=3)
    assert stats["tasks_total"] == 7, "限制 recent_limit=3 不应截断 total"
    assert len(stats["recent_tasks"]) == 3
    assert stats["running_total"] == 0
    assert stats["findings_total"] == 0


def test_dashboard_total_zero_when_empty(tmp_path) -> None:
    """空表时 tasks_total=0，不抛异常。"""
    app = _make_stack(tmp_path)
    stats = app.get_dashboard_stats(recent_limit=8)
    assert stats == {
        "tasks_total": 0,
        "running_total": 0,
        "findings_total": 0,
        "recent_tasks": [],
    }


def test_dashboard_running_total_independent(tmp_path) -> None:
    """running_total 走独立 count_tasks(status=RUNNING)，与 list 的 total 解耦。"""
    app = _make_stack(tmp_path)
    tasks = [app._task.create_task(goal=f"g{i}", task_type=TaskType.BLACKBOX) for i in range(3)]
    app._task.update_status(tasks[0], TaskStatus.RUNNING)

    stats = app.get_dashboard_stats(recent_limit=8)
    assert stats["tasks_total"] == 3
    assert stats["running_total"] == 1
