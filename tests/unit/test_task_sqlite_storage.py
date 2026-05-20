"""TaskSQLiteStorage 单测。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from argus_py.core.enums import (
    FindingSeverity,
    FindingType,
    StepResult,
    TaskStatus,
    TaskType,
)
from argus_py.core.exceptions import TaskError
from argus_py.infra.db import connect as _connect
from argus_py.infra.db import init_database
from argus_py.task.event import TimelineEvent
from argus_py.task.models import Finding, Task, TaskLog
from argus_py.task.storage import TaskSQLiteStorage


def _make_task(store: TaskSQLiteStorage, task_id: str, goal: str, **overrides: Any) -> Task:
    """创建并保存任务。"""
    task = Task(task_id=task_id, goal=goal, **overrides)
    store.save(task)
    return task


def _append_logs(store: TaskSQLiteStorage, task_id: str, count: int) -> None:
    """追加多条步骤日志。"""
    for i in range(count):
        store.append_log(task_id, TaskLog(step_number=i + 1, action="goto"))


def _append_findings(store: TaskSQLiteStorage, task_id: str, count: int) -> None:
    """追加多条发现项。"""
    for _ in range(count):
        store.append_finding(
            task_id, Finding(title="x", description="x", severity=FindingSeverity.INFO)
        )


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
        assert loaded.current_step == 0
        assert loaded.capture_screenshots is True
        assert loaded.parameters == {}
        assert loaded.logs == []
        assert loaded.findings == []

        # 存在性检查
        assert store.exists("t1")
        assert not store.exists("no-such")

        # 覆盖保存
        store.save(Task(task_id="t1", goal="更新后的目标"))
        assert store.load("t1").goal == "更新后的目标"

    def test_load_nonexistent_raises(self, store: TaskSQLiteStorage) -> None:
        with pytest.raises(TaskError, match="Task not found"):
            store.load("no-such-task")

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
        _make_task(store, "t1", "日志测试")
        store.append_log("t1", TaskLog(step_number=1, action="goto", result=StepResult.SUCCESS))
        loaded = store.load("t1")
        assert len(loaded.logs) == 1
        log = loaded.logs[0]
        assert log.step_number == 1
        assert log.action == "goto"
        assert log.result is StepResult.SUCCESS

    def test_append_finding(self, store: TaskSQLiteStorage) -> None:
        _make_task(store, "t1", "发现项测试")
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

    def test_appended_logs_and_findings_load(self, store: TaskSQLiteStorage) -> None:
        _make_task(store, "t1", "全量保存")
        _append_logs(store, "t1", 2)
        store.append_finding(
            "t1", Finding(title="观察项", description="正常", severity=FindingSeverity.INFO)
        )
        loaded = store.load("t1")
        assert len(loaded.logs) == 2
        assert len(loaded.findings) == 1

    def test_append_then_full_save_consistency(self, store: TaskSQLiteStorage) -> None:
        _make_task(store, "t1", "一致性")
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
        _make_task(store, "t1", "大量日志")
        _append_logs(store, "t1", 50)
        loaded = store.load("t1")
        assert len(loaded.logs) == 50
        assert loaded.logs[-1].step_number == 50

    def test_log_params_round_trip(self, store: TaskSQLiteStorage) -> None:
        _make_task(store, "t1", "参数测试")
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
        assert multi_store.count_tasks() == 5

    def test_list_ordering(self, multi_store: TaskSQLiteStorage) -> None:
        tasks = multi_store.list_tasks()
        times = [t.created_at for t in tasks]
        assert times == sorted(times, reverse=True)

    @pytest.mark.parametrize(
        ("limit", "offset", "expected"),
        [
            (2, 0, 2),
            (None, 2, 3),
            (None, 5, 0),
            (None, 3, 2),
            (2, 1, 2),
        ],
        ids=["limit", "offset", "offset_beyond", "offset_partial", "offset_and_limit"],
    )
    def test_list_pagination(
        self, multi_store: TaskSQLiteStorage, limit: int | None, offset: int, expected: int
    ) -> None:
        tasks = multi_store.list_tasks(limit=limit, offset=offset)
        assert len(tasks) == expected

    @pytest.mark.parametrize(
        ("status", "project_id", "expected_ids"),
        [
            ("completed", None, ["t2", "t1", "t0"]),
            (None, "proj-a", ["t4", "t2", "t0"]),
            ("pending", "proj-b", ["t3"]),
        ],
        ids=["by_status", "by_project", "combined"],
    )
    def test_list_filters(
        self,
        multi_store: TaskSQLiteStorage,
        status: str | None,
        project_id: str | None,
        expected_ids: list[str],
    ) -> None:
        tasks = multi_store.list_tasks(status=status, project_id=project_id)
        assert [t.task_id for t in tasks] == expected_ids

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

    @pytest.fixture
    def summary_store(self, tmp_path: Path) -> TaskSQLiteStorage:
        return TaskSQLiteStorage(tmp_path / "summary.db")

    def test_summary_has_no_logs_or_findings(self, summary_store: TaskSQLiteStorage) -> None:
        _make_task(summary_store, "t1", "摘要测试")
        _append_logs(summary_store, "t1", 1)
        _append_findings(summary_store, "t1", 1)
        summaries, total = summary_store.list_task_summaries()
        assert len(summaries) == 1
        assert total == 1
        assert summaries[0].logs == []
        assert summaries[0].findings == []

    @pytest.mark.parametrize(
        ("n_logs", "n_findings", "expected_step", "expected_count"),
        [
            (2, 0, 2, 0),
            (0, 3, 0, 3),
            (3, 2, 3, 2),
        ],
        ids=["current_step", "finding_count", "mixed"],
    )
    def test_summary_step_and_count(
        self,
        summary_store: TaskSQLiteStorage,
        n_logs: int,
        n_findings: int,
        expected_step: int,
        expected_count: int,
    ) -> None:
        _make_task(summary_store, "t1", "摘要")
        _append_logs(summary_store, "t1", n_logs)
        _append_findings(summary_store, "t1", n_findings)
        summaries, total = summary_store.list_task_summaries()
        assert len(summaries) == 1
        assert total == 1
        assert summaries[0].current_step == expected_step
        assert summaries[0].finding_count == expected_count
        full = summary_store.load("t1")
        assert full.current_step == expected_step
        assert full.finding_count == expected_count

    def test_summary_multiple_tasks(self, tmp_path: Path) -> None:
        store = TaskSQLiteStorage(tmp_path / "multi_summary.db")
        for i in range(3):
            _make_task(store, f"t{i}", f"任务{i}")
            _append_logs(store, f"t{i}", i + 1)
            _append_findings(store, f"t{i}", i + 1)
        summaries, total = store.list_task_summaries()
        assert len(summaries) == 3
        assert total == 3
        step_map = {s.task_id: s.current_step for s in summaries}
        find_map = {s.task_id: s.finding_count for s in summaries}
        assert step_map["t0"] == 1
        assert step_map["t1"] == 2
        assert step_map["t2"] == 3
        assert find_map["t0"] == 1
        assert find_map["t1"] == 2
        assert find_map["t2"] == 3

    def test_summary_query_count_is_constant_no_n_plus_one(self, tmp_path: Path) -> None:
        """N+1 回归：查询次数与任务行数无关。

        旧实现用相关子查询 ``(SELECT COUNT(*) FROM findings ...)``，每行触发
        一次额外索引查询；新实现两步聚合，无论页大小都恒 2 条 SELECT。
        """
        store = TaskSQLiteStorage(tmp_path / "n1_guard.db")
        for i in range(20):
            _make_task(store, f"t{i:02d}", f"任务{i}")
            _append_findings(store, f"t{i:02d}", 3)

        select_count = 0

        def _count_select(sql: str) -> None:
            nonlocal select_count
            stripped = sql.strip().lstrip("(").lstrip().upper()
            if stripped.startswith("SELECT"):
                select_count += 1

        original_new_conn = store._tasks._pool._new_conn

        def traced_new_conn(read_only: bool):  # noqa: FBT001
            conn = original_new_conn(read_only)
            conn.set_trace_callback(_count_select)
            return conn

        store._tasks._pool._new_conn = traced_new_conn  # type: ignore[method-assign]
        try:
            summaries, total = store.list_task_summaries()
        finally:
            store._tasks._pool._new_conn = original_new_conn  # type: ignore[method-assign]

        assert total == 20
        assert len(summaries) == 20
        # 期望恰好 2 条 SELECT：一页 tasks（含 total）+ 一次聚合 findings count。
        # 留 1 条容差以适配 sqlite 内部偶发的辅助查询。
        assert select_count <= 3, f"疑似 N+1：执行了 {select_count} 条 SELECT"


class TestCrossInstance:
    """跨实例一致性。"""

    def test_cross_instance(self, tmp_path: Path) -> None:
        db_path = tmp_path / "shared.db"
        s1 = TaskSQLiteStorage(db_path)
        s1.save(Task(task_id="t1", goal="跨实例"))
        s1.append_log("t1", TaskLog(step_number=1, action="goto"))

        # 另一实例可读取
        s2 = TaskSQLiteStorage(db_path)
        loaded = s2.load("t1")
        assert loaded.goal == "跨实例"
        assert len(loaded.logs) == 1

        # 两实例先后追加互不冲突
        s2.append_log("t1", TaskLog(step_number=2, action="click"))
        final = s1.load("t1")
        assert len(final.logs) == 2


class TestEdgeCases:
    """边界情况。"""

    @pytest.mark.parametrize(
        "preset_logs",
        [True, False],
        ids=["explicit_empty", "implicit_empty"],
    )
    def test_empty_logs_and_findings(self, store: TaskSQLiteStorage, preset_logs: bool) -> None:
        task = Task(task_id="t1", goal="空列表测试")
        if preset_logs:
            task.logs = []
            task.findings = []
        store.save(task)
        loaded = store.load("t1")
        assert loaded.logs == []
        assert loaded.findings == []


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

    @pytest.mark.parametrize(
        "add_current_step",
        [False, True],
        ids=["add_missing_column", "keep_existing_column"],
    )
    def test_migrate_tasks(self, tmp_path: Path, add_current_step: bool) -> None:
        db_path = tmp_path / "migrate.db"
        conn = _connect(db_path)
        schema = self._OLD_TASK_COLS
        if add_current_step:
            schema += ", current_step INTEGER NOT NULL DEFAULT 0"
        conn.execute(f"CREATE TABLE tasks ({schema})")
        conn.close()

        init_database(db_path)

        conn2 = _connect(db_path)
        cols = {row["name"] for row in conn2.execute("PRAGMA table_info(tasks)").fetchall()}
        assert "current_step" in cols
        if add_current_step:
            matches = [
                row
                for row in conn2.execute("PRAGMA table_info(tasks)")
                if row["name"] == "current_step"
            ]
            assert len(matches) == 1
        conn2.close()


class TestTimelineEvents:
    """时间线事件存储。"""

    def _make_event(
        self,
        task_id: str = "t1",
        event_type: str = "start",
        phase: str = "task",
        **overrides: Any,
    ) -> TimelineEvent:
        from argus_py.core.ids import generate_id

        return TimelineEvent(
            event_id=generate_id("evt"),
            task_id=task_id,
            event_type=event_type,
            phase=phase,
            **overrides,
        )

    def test_append_and_load(self, store: TaskSQLiteStorage) -> None:
        _make_task(store, "t1", "时间线测试")
        store.append_event(self._make_event())
        store.append_event(self._make_event(event_type="complete", phase="task"))
        events = store.load_events("t1")
        assert len(events) == 2
        assert events[0].event_type == "start"
        assert events[1].event_type == "complete"

    def test_load_order(self, store: TaskSQLiteStorage) -> None:
        _make_task(store, "t1", "排序测试")
        from datetime import datetime, timedelta, timezone

        base = datetime.now(timezone.utc)
        store.append_event(self._make_event(event_type="start", created_at=base))
        store.append_event(
            self._make_event(event_type="action", created_at=base + timedelta(seconds=1))
        )
        store.append_event(
            self._make_event(event_type="complete", created_at=base + timedelta(seconds=2))
        )
        events = store.load_events("t1")
        assert [e.event_type for e in events] == ["start", "action", "complete"]

    def test_load_empty(self, store: TaskSQLiteStorage) -> None:
        assert store.load_events("no-such") == []

    def test_delete(self, store: TaskSQLiteStorage) -> None:
        _make_task(store, "t1", "删除测试")
        store.append_event(self._make_event())
        store.delete_events("t1")
        assert store.load_events("t1") == []

    def test_delete_other_task_unaffected(self, store: TaskSQLiteStorage) -> None:
        _make_task(store, "t1", "任务A")
        _make_task(store, "t2", "任务B")
        store.append_event(self._make_event(task_id="t1"))
        store.append_event(self._make_event(task_id="t2"))
        store.delete_events("t1")
        assert len(store.load_events("t1")) == 0
        assert len(store.load_events("t2")) == 1

    def test_event_data_round_trip(self, store: TaskSQLiteStorage) -> None:
        _make_task(store, "t1", "数据测试")
        store.append_event(
            self._make_event(
                event_type="planner_result",
                phase="planner",
                step_number=3,
                summary="规划完成",
                data={"stepCount": 5, "planSummary": "测试计划"},
            )
        )
        events = store.load_events("t1")
        assert len(events) == 1
        e = events[0]
        assert e.event_type == "planner_result"
        assert e.phase == "planner"
        assert e.step_number == 3
        assert e.summary == "规划完成"
        assert e.data == {"stepCount": 5, "planSummary": "测试计划"}

    def test_event_with_non_existent_task(self, store: TaskSQLiteStorage) -> None:
        """events 通过 FK 引用 tasks，不存在的 task_id 会触发 IntegrityError。"""
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            store.append_event(self._make_event(task_id="no-such"))

    def test_cross_instance(self, tmp_path: Path) -> None:
        _make_task(TaskSQLiteStorage(tmp_path / "cross.db"), "t1", "跨实例")
        s1 = TaskSQLiteStorage(tmp_path / "cross.db")
        s1.append_event(self._make_event(task_id="t1"))
        s2 = TaskSQLiteStorage(tmp_path / "cross.db")
        events = s2.load_events("t1")
        assert len(events) == 1
