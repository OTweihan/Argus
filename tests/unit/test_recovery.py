"""测试服务启动时中断任务恢复。"""

from __future__ import annotations

import pytest

from argus_py.core.enums import TaskStatus
from argus_py.infra.recovery import INTERRUPTED_MESSAGE, recover_interrupted_tasks
from argus_py.task.service import TaskService
from argus_py.task.storage import TaskFileStorage


def _make_service(tmp_path) -> TaskService:
    return TaskService(TaskFileStorage(tmp_path / "tasks"))


def _list_statuses(service: TaskService) -> dict[str, TaskStatus]:
    return {t.task_id: t.status for t in service.list_tasks()}


def test_recover_sets_running_to_failed(tmp_path):
    service = _make_service(tmp_path)
    t = service.create_task("running task", start_url="https://example.com")
    service.start_task(t)  # running

    count = recover_interrupted_tasks(service)

    assert count == 1
    updated = service.get_task(t.task_id)
    assert updated.status is TaskStatus.FAILED
    assert updated.error_message == INTERRUPTED_MESSAGE
    assert updated.completed_at is not None
    assert updated.completed_at > updated.started_at


@pytest.mark.parametrize(
    ("setup_status"),
    [
        None,
        TaskStatus.PENDING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.CANCELLED,
    ],
    ids=["empty", "pending", "completed", "failed", "timeout", "cancelled"],
)
def test_recover_skips_non_running(tmp_path, setup_status: TaskStatus | None) -> None:
    service = _make_service(tmp_path)
    task_id: str | None = None
    if setup_status is None:
        pass
    elif setup_status is TaskStatus.PENDING:
        t = service.create_task("task", start_url="https://example.com")
        task_id = t.task_id
    else:
        t = service.create_task("task", start_url="https://example.com")
        service.start_task(t)
        service.update_status(t, setup_status)
        task_id = t.task_id

    assert recover_interrupted_tasks(service) == 0

    if task_id is not None:
        assert service.get_task(task_id).status is setup_status


def test_recover_handles_mixed_states(tmp_path):
    service = _make_service(tmp_path)

    running = service.create_task("running", start_url="https://example.com")
    service.start_task(running)

    pending = service.create_task("pending", start_url="https://example.com")

    completed = service.create_task("completed", start_url="https://example.com")
    service.start_task(completed)
    service.complete_task(completed)

    count = recover_interrupted_tasks(service)

    assert count == 1
    assert service.get_task(running.task_id).status is TaskStatus.FAILED
    assert service.get_task(pending.task_id).status is TaskStatus.PENDING
    assert service.get_task(completed.task_id).status is TaskStatus.COMPLETED
