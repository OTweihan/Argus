"""测试服务启动时中断任务恢复。"""

from __future__ import annotations

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


def test_recover_skips_pending(tmp_path):
    service = _make_service(tmp_path)
    t = service.create_task("pending task", start_url="https://example.com")

    count = recover_interrupted_tasks(service)

    assert count == 0
    assert service.get_task(t.task_id).status is TaskStatus.PENDING


def test_recover_skips_terminal_states(tmp_path):
    service = _make_service(tmp_path)

    tasks = {}
    for status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED):
        t = service.create_task(f"{status.value} task", start_url="https://example.com")
        service.start_task(t)
        service.update_status(t, status)
        tasks[status] = t.task_id

    count = recover_interrupted_tasks(service)

    assert count == 0
    for status, task_id in tasks.items():
        assert service.get_task(task_id).status is status


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


def test_recover_returns_zero_when_none_running(tmp_path):
    service = _make_service(tmp_path)
    assert recover_interrupted_tasks(service) == 0


def test_recover_writes_completed_at(tmp_path):
    service = _make_service(tmp_path)
    t = service.create_task("running", start_url="https://example.com")
    service.start_task(t)

    recover_interrupted_tasks(service)

    recovered = service.get_task(t.task_id)
    assert recovered.completed_at is not None
    # completed_at > started_at
    assert recovered.completed_at > recovered.started_at  # type: ignore[operator]
