"""TaskTimelineService 单测：时间线事件的创建、持久化、发布。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from argus_py.task.event import TaskTimelineService
from argus_py.task.storage import TaskSQLiteStorage


def _make_task_in_db(store: TaskSQLiteStorage, task_id: str) -> None:
    """在 SQLite 中创建一条任务记录（events FK 依赖 tasks）。"""
    from argus_py.task.models import Task

    store.save(Task(task_id=task_id, goal="时间线服务测试"))


@pytest.fixture
def store(tmp_path: Path) -> TaskSQLiteStorage:
    return TaskSQLiteStorage(tmp_path / "test.db")


@pytest.fixture
def service(store: TaskSQLiteStorage) -> TaskTimelineService:
    return TaskTimelineService(store)


class TestEmit:
    """emit() 方法。"""

    def test_emit_creates_event_with_fields(
        self, service: TaskTimelineService, store: TaskSQLiteStorage
    ) -> None:
        _make_task_in_db(store, "t1")
        event = service.emit("t1", "planner_start", "planner", step_number=1, summary="开始规划")
        assert event.task_id == "t1"
        assert event.event_type == "planner_start"
        assert event.phase == "planner"
        assert event.step_number == 1
        assert event.summary == "开始规划"
        assert event.event_id.startswith("evt-")

    def test_emit_persists_to_storage(
        self, service: TaskTimelineService, store: TaskSQLiteStorage
    ) -> None:
        _make_task_in_db(store, "t1")
        service.emit("t1", "action", "executor", summary="点击按钮")
        events = store.load_events("t1")
        assert len(events) == 1
        assert events[0].event_type == "action"

    def test_emit_with_data(self, service: TaskTimelineService, store: TaskSQLiteStorage) -> None:
        _make_task_in_db(store, "t1")
        data = {"stepCount": 3, "planSummary": "测试"}
        service.emit("t1", "planner_result", "planner", step_number=2, data=data)
        events = store.load_events("t1")
        assert events[0].data == data
        assert events[0].step_number == 2

    def test_emit_multiple_events_order(
        self, service: TaskTimelineService, store: TaskSQLiteStorage
    ) -> None:
        _make_task_in_db(store, "t1")
        service.emit("t1", "start", "task", summary="开始")
        service.emit("t1", "action", "executor", step_number=1, summary="动作1")
        service.emit("t1", "complete", "task", summary="完成")
        events = store.load_events("t1")
        assert [e.event_type for e in events] == ["start", "action", "complete"]


class TestPublish:
    """emit() 通过 event_publisher 发布。"""

    def test_publisher_called_with_correct_args(self, store: TaskSQLiteStorage) -> None:
        received: list[tuple[str, str, dict[str, Any]]] = []

        def publisher(event_type: str, task_id: str, data: dict[str, Any]) -> None:
            received.append((event_type, task_id, data))

        svc = TaskTimelineService(store, event_publisher=publisher)
        _make_task_in_db(store, "t1")
        svc.emit(
            "t1",
            "planner_start",
            "planner",
            step_number=1,
            summary="开始规划",
            data={"goal": "测试"},
        )

        assert len(received) == 1
        event_type, task_id, data = received[0]
        assert event_type == "task.timeline.planner"
        assert task_id == "t1"
        assert data["eventId"].startswith("evt-")
        assert data["eventType"] == "planner_start"
        assert data["phase"] == "planner"
        assert data["summary"] == "开始规划"
        assert data["data"] == {"goal": "测试"}

    def test_publisher_not_called_when_none(
        self, service: TaskTimelineService, store: TaskSQLiteStorage
    ) -> None:
        _make_task_in_db(store, "t1")
        # should not raise
        service.emit("t1", "start", "task", summary="无发布器")

    def test_publisher_called_multiple_times(self, store: TaskSQLiteStorage) -> None:
        count = 0

        def publisher(event_type: str, task_id: str, data: dict[str, Any]) -> None:
            nonlocal count
            count += 1

        svc = TaskTimelineService(store, event_publisher=publisher)
        _make_task_in_db(store, "t1")
        svc.emit("t1", "start", "task")
        svc.emit("t1", "action", "executor")
        svc.emit("t1", "complete", "task")
        assert count == 3

    def test_publisher_receives_task_timeline_prefix(self, store: TaskSQLiteStorage) -> None:
        received_types: list[str] = []

        def publisher(event_type: str, task_id: str, data: dict[str, Any]) -> None:
            received_types.append(event_type)

        svc = TaskTimelineService(store, event_publisher=publisher)
        _make_task_in_db(store, "t1")
        svc.emit("t1", "planner_start", "planner")
        svc.emit("t1", "action", "executor")
        svc.emit("t1", "complete", "task")

        assert received_types == [
            "task.timeline.planner",
            "task.timeline.executor",
            "task.timeline.task",
        ]


class TestListAndDelete:
    """list_by_task / delete_by_task。"""

    def test_list_by_task(self, service: TaskTimelineService, store: TaskSQLiteStorage) -> None:
        _make_task_in_db(store, "t1")
        service.emit("t1", "start", "task")
        service.emit("t1", "complete", "task")
        events = service.list_by_task("t1")
        assert len(events) == 2

    def test_list_empty(self, service: TaskTimelineService) -> None:
        assert service.list_by_task("no-such") == []

    def test_list_isolated_by_task(
        self, service: TaskTimelineService, store: TaskSQLiteStorage
    ) -> None:
        _make_task_in_db(store, "t1")
        _make_task_in_db(store, "t2")
        service.emit("t1", "start", "task")
        service.emit("t2", "start", "task")
        assert len(service.list_by_task("t1")) == 1
        assert len(service.list_by_task("t2")) == 1

    def test_delete_by_task(self, service: TaskTimelineService, store: TaskSQLiteStorage) -> None:
        _make_task_in_db(store, "t1")
        service.emit("t1", "start", "task")
        service.delete_by_task("t1")
        assert service.list_by_task("t1") == []

    def test_delete_isolated_by_task(
        self, service: TaskTimelineService, store: TaskSQLiteStorage
    ) -> None:
        _make_task_in_db(store, "t1")
        _make_task_in_db(store, "t2")
        service.emit("t1", "start", "task")
        service.emit("t2", "start", "task")
        service.delete_by_task("t1")
        assert len(service.list_by_task("t2")) == 1
