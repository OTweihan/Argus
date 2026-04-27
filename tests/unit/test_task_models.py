from argus_py.core.enums import TaskStatus
from argus_py.task.models import Task
from argus_py.task.status import can_transition


def test_task_defaults():
    task = Task(goal="打开页面", start_url="https://example.com")

    assert task.status is TaskStatus.PENDING
    assert task.current_step == 0
    assert task.task_id.startswith("task-")


def test_status_transition():
    assert can_transition(TaskStatus.PENDING, TaskStatus.RUNNING)
    assert not can_transition(TaskStatus.COMPLETED, TaskStatus.RUNNING)
