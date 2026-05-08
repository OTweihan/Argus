"""TaskSQLiteStorage 单测。"""

from __future__ import annotations

from pathlib import Path

import pytest

from argus_py.core.enums import (
    FindingSeverity,
    FindingType,
    StepResult,
    TaskStatus,
    TaskType,
)
from argus_py.core.exceptions import TaskError
from argus_py.infra.db import connect as _connect, init_database
from argus_py.task.models import Finding, Task, TaskLog
from argus_py.task.storage import TaskSQLiteStorage


@pytest.fixture
def store(tmp_path: Path) -> TaskSQLiteStorage:
    """使用临时数据库的存储实例。"""
    return TaskSQLiteStorage(tmp_path / "test.db")


class TestCRUD:
    """增删改查基础功能。"""

    def test_save_and_load(self, store: TaskSQLiteStorage) -> None:
        task = Task(task_id="t1", goal="测试任务", start_url="https://example.com")
        store.save(task)
        loaded = store.load("t1")
        assert loaded.task_id == "t1"
        assert loaded.goal == "测试任务"
        assert loaded.start_url == "https://example.com"
        assert loaded.status is TaskStatus.PENDING
        assert loaded.task_type is TaskType.BLACKBOX

    def test_load_nonexistent_raises(self, store: TaskSQLiteStorage) -> None:
        with pytest.raises(TaskError, match="Task not found"):
            store.load("no-such-task")

    def test_exists(self, store: TaskSQLiteStorage) -> None:
        assert not store.exists("t1")
        store.save(Task(task_id="t1", goal="g"))
        assert store.exists("t1")

    def test_overwrite(self, store: TaskSQLiteStorage) -> None:
        store.save(Task(task_id="t1", goal="原始目标"))
        store.save(Task(task_id="t1", goal="更新后的目标"))
        loaded = store.load("t1")
        assert loaded.goal == "更新后的目标"

    def test_enum_round_trip(self, store: TaskSQLiteStorage) -> None:
        task = Task(
            task_id="t1",
            goal="枚举测试",
            task_type=TaskType.BLACKBOX,
            status=TaskStatus.CANCELLED,
            parameters={"key": "val"},
        )
        store.save(task)
        loaded = store.load("t1")
        assert loaded.task_type is TaskType.BLACKBOX
        assert loaded.status is TaskStatus.CANCELLED
        assert loaded.parameters == {"key": "val"}

    def test_all_fields_round_trip(self, store: TaskSQLiteStorage) -> None:
        import datetime

        from argus_py.task.models import utc_now

        now = utc_now()
        later = now + datetime.timedelta(seconds=10)
        task = Task(
            task_id="t1",
            goal="全字段",
            start_url="https://example.com",
            task_type=TaskType.WHITEBOX,
            status=TaskStatus.COMPLETED,
            project_id="proj-1",
            max_steps=99,
            timeout_seconds=600,
            capture_screenshots=False,
            parameters={"mode": "deep"},
            created_at=now,
            started_at=now,
            completed_at=later,
            report_path="/tmp/report.html",
            result_summary="全部通过",
            error_message="无错误",
        )
        store.save(task)
        loaded = store.load("t1")
        assert loaded.project_id == "proj-1"
        assert loaded.max_steps == 99
        assert loaded.timeout_seconds == 600
        assert loaded.capture_screenshots is False
        assert loaded.report_path == "/tmp/report.html"
        assert loaded.result_summary == "全部通过"
        assert loaded.error_message == "无错误"
        assert loaded.started_at == now
        assert loaded.completed_at == later


class TestLogsAndFindings:
    """步骤日志和发现项。"""

    def test_append_log(self, store: TaskSQLiteStorage) -> None:
        store.save(Task(task_id="t1", goal="日志测试"))
        store.append_log("t1", TaskLog(step_number=1, action="goto", result=StepResult.SUCCESS))
        loaded = store.load("t1")
        assert len(loaded.logs) == 1
        log = loaded.logs[0]
        assert log.step_number == 1
        assert log.action == "goto"
        assert log.result is StepResult.SUCCESS

    def test_append_finding(self, store: TaskSQLiteStorage) -> None:
        store.save(Task(task_id="t1", goal="发现项测试"))
        store.append_finding(
            "t1",
            Finding(
                title="性能问题",
                description="加载超时",
                severity=FindingSeverity.HIGH,
                finding_type=FindingType.PERFORMANCE,
            ),
        )
        loaded = store.load("t1")
        assert len(loaded.findings) == 1
        finding = loaded.findings[0]
        assert finding.title == "性能问题"
        assert finding.severity is FindingSeverity.HIGH
        assert finding.finding_type is FindingType.PERFORMANCE

    def test_full_save_with_logs_and_findings(self, store: TaskSQLiteStorage) -> None:
        task = Task(task_id="t1", goal="全量保存")
        task.logs.append(TaskLog(step_number=1, action="goto", result=StepResult.SUCCESS))
        task.logs.append(TaskLog(step_number=2, action="click", result=StepResult.SUCCESS))
        task.findings.append(
            Finding(title="观察项", description="正常", severity=FindingSeverity.INFO)
        )
        store.save(task)
        loaded = store.load("t1")
        assert len(loaded.logs) == 2
        assert len(loaded.findings) == 1

    def test_append_then_full_save_consistency(self, store: TaskSQLiteStorage) -> None:
        store.save(Task(task_id="t1", goal="一致性"))
        store.append_log("t1", TaskLog(step_number=1, action="goto", result=StepResult.SUCCESS))
        store.append_finding(
            "t1", Finding(title="问题", description="bug", severity=FindingSeverity.HIGH)
        )
        task = store.load("t1")
        task.status = TaskStatus.COMPLETED
        store.save(task)
        loaded = store.load("t1")
        assert loaded.status is TaskStatus.COMPLETED
        assert len(loaded.logs) == 1
        assert len(loaded.findings) == 1

    def test_many_logs(self, store: TaskSQLiteStorage) -> None:
        store.save(Task(task_id="t1", goal="大量日志"))
        for i in range(50):
            store.append_log("t1", TaskLog(step_number=i + 1, action=f"step_{i}"))
        loaded = store.load("t1")
        assert len(loaded.logs) == 50
        assert loaded.logs[-1].step_number == 50

    def test_log_params_round_trip(self, store: TaskSQLiteStorage) -> None:
        store.save(Task(task_id="t1", goal="参数测试"))
        store.append_log(
            "t1",
            TaskLog(
                step_number=1,
                action="fill",
                params={"selector": "#username", "text": "hello"},
            ),
        )
        loaded = store.load("t1")
        assert loaded.logs[0].params == {"selector": "#username", "text": "hello"}


class TestListAndCount:
    """列表和计数。"""

    @pytest.fixture
    def multi_store(self, tmp_path: Path) -> TaskSQLiteStorage:
        s = TaskSQLiteStorage(tmp_path / "multi.db")
        for i in range(5):
            s.save(
                Task(
                    task_id=f"t{i}",
                    goal=f"任务{i}",
                    status=TaskStatus.COMPLETED if i < 3 else TaskStatus.PENDING,
                    project_id="proj-a" if i % 2 == 0 else "proj-b",
                )
            )
        return s

    def test_list_all(self, multi_store: TaskSQLiteStorage) -> None:
        tasks = multi_store.list_tasks()
        assert len(tasks) == 5

    def test_list_ordering(self, multi_store: TaskSQLiteStorage) -> None:
        tasks = multi_store.list_tasks()
        times = [t.created_at for t in tasks]
        assert times == sorted(times, reverse=True)

    def test_list_limit(self, multi_store: TaskSQLiteStorage) -> None:
        tasks = multi_store.list_tasks(limit=2)
        assert len(tasks) == 2

    def test_list_offset(self, multi_store: TaskSQLiteStorage) -> None:
        tasks = multi_store.list_tasks(offset=2)
        assert len(tasks) == 3

    def test_list_offset_without_limit(self, multi_store: TaskSQLiteStorage) -> None:
        tasks = multi_store.list_tasks(offset=5)
        assert len(tasks) == 0
        tasks = multi_store.list_tasks(offset=3)
        assert len(tasks) == 2

    def test_list_offset_and_limit(self, multi_store: TaskSQLiteStorage) -> None:
        tasks = multi_store.list_tasks(offset=1, limit=2)
        assert len(tasks) == 2

    def test_count_all(self, multi_store: TaskSQLiteStorage) -> None:
        assert multi_store.count_tasks() == 5

    def test_filter_by_status(self, multi_store: TaskSQLiteStorage) -> None:
        tasks = multi_store.list_tasks(status="completed")
        assert len(tasks) == 3
        assert all(t.status is TaskStatus.COMPLETED for t in tasks)

    def test_filter_by_project_id(self, multi_store: TaskSQLiteStorage) -> None:
        tasks = multi_store.list_tasks(project_id="proj-a")
        assert len(tasks) == 3
        assert all(t.project_id == "proj-a" for t in tasks)

    def test_filter_combined(self, multi_store: TaskSQLiteStorage) -> None:
        tasks = multi_store.list_tasks(status="pending", project_id="proj-b")
        assert len(tasks) == 1
        assert tasks[0].task_id == "t3"

    def test_filter_and_paginate(self, multi_store: TaskSQLiteStorage) -> None:
        tasks = multi_store.list_tasks(status="completed", offset=1, limit=1)
        assert len(tasks) == 1

    def test_count_with_filter(self, multi_store: TaskSQLiteStorage) -> None:
        assert multi_store.count_tasks(status="completed") == 3
        assert multi_store.count_tasks(project_id="proj-b") == 2
        assert multi_store.count_tasks(status="pending", project_id="proj-b") == 1

    def test_empty_db_list(self, store: TaskSQLiteStorage) -> None:
        assert store.list_tasks() == []
        assert store.count_tasks() == 0


class TestSummaries:
    """摘要查询（list_task_summaries）。"""

    def test_summary_has_no_logs_or_findings(self, tmp_path: Path) -> None:
        store = TaskSQLiteStorage(tmp_path / "summary.db")
        store.save(Task(task_id="t1", goal="摘要测试"))
        store.append_log("t1", TaskLog(step_number=1, action="goto"))
        store.append_finding(
            "t1", Finding(title="x", description="x", severity=FindingSeverity.INFO)
        )
        summaries = store.list_task_summaries()
        assert len(summaries) == 1
        assert summaries[0].logs == []
        assert summaries[0].findings == []

    def test_summary_current_step_from_db(self, tmp_path: Path) -> None:
        store = TaskSQLiteStorage(tmp_path / "step.db")
        store.save(Task(task_id="t1", goal="步骤测试"))
        store.append_log("t1", TaskLog(step_number=1, action="goto"))
        store.append_log("t1", TaskLog(step_number=2, action="click"))
        summaries = store.list_task_summaries()
        assert summaries[0].current_step == 2

    def test_summary_finding_count_from_db(self, tmp_path: Path) -> None:
        store = TaskSQLiteStorage(tmp_path / "finding.db")
        store.save(Task(task_id="t1", goal="问题测试"))
        store.append_finding(
            "t1", Finding(title="a", description="x", severity=FindingSeverity.HIGH)
        )
        store.append_finding(
            "t1", Finding(title="b", description="y", severity=FindingSeverity.LOW)
        )
        store.append_finding(
            "t1", Finding(title="c", description="z", severity=FindingSeverity.MEDIUM)
        )
        summaries = store.list_task_summaries()
        assert summaries[0].finding_count == 3

    def test_summary_step_and_count_after_mixed_updates(self, tmp_path: Path) -> None:
        store = TaskSQLiteStorage(tmp_path / "mixed.db")
        store.save(Task(task_id="t1", goal="混合"))
        # 3 logs + 2 findings
        for i in range(3):
            store.append_log("t1", TaskLog(step_number=i + 1, action=f"step_{i}"))
        store.append_finding(
            "t1", Finding(title="a", description="x", severity=FindingSeverity.HIGH)
        )
        store.append_finding(
            "t1", Finding(title="b", description="y", severity=FindingSeverity.LOW)
        )
        summaries = store.list_task_summaries()
        assert summaries[0].current_step == 3
        assert summaries[0].finding_count == 2
        # Full load should also match
        full = store.load("t1")
        assert full.current_step == 3
        assert full.finding_count == 2

    def test_summary_multiple_tasks(self, tmp_path: Path) -> None:
        store = TaskSQLiteStorage(tmp_path / "multi_summary.db")
        for i in range(3):
            store.save(Task(task_id=f"t{i}", goal=f"任务{i}"))
            for j in range(i + 1):
                store.append_log(f"t{i}", TaskLog(step_number=j + 1, action="goto"))
                store.append_finding(
                    f"t{i}",
                    Finding(title=f"f_{j}", description="x", severity=FindingSeverity.INFO),
                )
        summaries = store.list_task_summaries()
        assert len(summaries) == 3
        step_map = {s.task_id: s.current_step for s in summaries}
        find_map = {s.task_id: s.finding_count for s in summaries}
        assert step_map["t0"] == 1
        assert step_map["t1"] == 2
        assert step_map["t2"] == 3
        assert find_map["t0"] == 1
        assert find_map["t1"] == 2
        assert find_map["t2"] == 3


class TestCrossInstance:
    """跨实例一致性。"""

    def test_reload_from_different_instance(self, tmp_path: Path) -> None:
        db_path = tmp_path / "shared.db"
        s1 = TaskSQLiteStorage(db_path)
        s1.save(Task(task_id="t1", goal="跨实例"))
        s1.append_log("t1", TaskLog(step_number=1, action="goto"))

        s2 = TaskSQLiteStorage(db_path)
        loaded = s2.load("t1")
        assert loaded.goal == "跨实例"
        assert len(loaded.logs) == 1

    def test_concurrent_append(self, tmp_path: Path) -> None:
        db_path = tmp_path / "shared.db"
        s1 = TaskSQLiteStorage(db_path)
        s2 = TaskSQLiteStorage(db_path)
        s1.save(Task(task_id="t1", goal="并发"))
        s1.append_log("t1", TaskLog(step_number=1, action="goto"))
        s2.append_log("t1", TaskLog(step_number=2, action="click"))
        loaded = s1.load("t1")
        assert len(loaded.logs) == 2


class TestEdgeCases:
    """边界情况。"""

    def test_save_empty_logs_and_findings(self, store: TaskSQLiteStorage) -> None:
        task = Task(task_id="t1", goal="空列表")
        task.logs = []
        task.findings = []
        store.save(task)
        loaded = store.load("t1")
        assert loaded.logs == []
        assert loaded.findings == []

    def test_load_without_logs_or_findings(self, store: TaskSQLiteStorage) -> None:
        store.save(Task(task_id="t1", goal="仅有任务"))
        loaded = store.load("t1")
        assert loaded.logs == []
        assert loaded.findings == []

    def test_capture_screenshots_default(self, store: TaskSQLiteStorage) -> None:
        store.save(Task(task_id="t1", goal="截图默认值"))
        loaded = store.load("t1")
        assert loaded.capture_screenshots is True

    def test_parameters_default_empty_dict(self, store: TaskSQLiteStorage) -> None:
        store.save(Task(task_id="t1", goal="参数默认值"))
        loaded = store.load("t1")
        assert loaded.parameters == {}


class TestMigration:
    """表结构迁移。"""

    _OLD_TASK_COLS = """
      task_id TEXT PRIMARY KEY,
      goal TEXT NOT NULL,
      start_url TEXT,
      task_type TEXT NOT NULL,
      status TEXT NOT NULL,
      project_id TEXT,
      max_steps INTEGER NOT NULL DEFAULT 20,
      timeout_seconds INTEGER NOT NULL DEFAULT 300,
      capture_screenshots INTEGER NOT NULL DEFAULT 1,
      parameters_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      started_at TEXT,
      completed_at TEXT,
      report_path TEXT,
      result_summary TEXT,
      error_message TEXT
    """

    def test_migrate_tasks_adds_missing_current_step(self, tmp_path: Path) -> None:
        db_path = tmp_path / "migrate.db"
        conn = _connect(db_path)
        conn.execute(f"CREATE TABLE tasks ({self._OLD_TASK_COLS})")
        conn.close()

        init_database(db_path)

        conn2 = _connect(db_path)
        cols = {row["name"] for row in conn2.execute("PRAGMA table_info(tasks)").fetchall()}
        conn2.close()
        assert "current_step" in cols

    def test_migrate_tasks_does_not_break_existing_current_step(self, tmp_path: Path) -> None:
        """已有 current_step 的表，init_database 不应报错也不应重复添加。"""
        db_path = tmp_path / "noop_migrate.db"
        conn = _connect(db_path)
        conn.execute(
            f"CREATE TABLE tasks ({self._OLD_TASK_COLS}, current_step INTEGER NOT NULL DEFAULT 0)"
        )
        conn.close()

        init_database(db_path)

        conn2 = _connect(db_path)
        cols = {row["name"] for row in conn2.execute("PRAGMA table_info(tasks)").fetchall()}
        assert "current_step" in cols
        current_step_cols = [
            row for row in conn2.execute("PRAGMA table_info(tasks)") if row["name"] == "current_step"
        ]
        assert len(current_step_cols) == 1
        conn2.close()
