import pytest
from argus_py.config.models import ModelConfig
from argus_py.core.enums import StepResult, TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.execution.runner import TaskRunner
from argus_py.report.generator import ReportGenerator
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.log import TaskLogService
from argus_py.task.models import Task, TaskLog
from argus_py.task.read import TaskReadService
from argus_py.task.status import can_transition
from argus_py.task.storage import TaskFileStorage
from argus_py.utils.jsonx import to_jsonable


def test_task_defaults():
    task = Task(goal="打开页面", start_url="https://example.com")

    assert task.status is TaskStatus.PENDING
    assert task.current_step == 0
    assert task.task_id.startswith("task-")


def test_status_transition():
    assert can_transition(TaskStatus.PENDING, TaskStatus.RUNNING)
    assert not can_transition(TaskStatus.COMPLETED, TaskStatus.RUNNING)


def test_task_from_dict_restores_nested_models():
    task = Task(goal="打开页面", start_url="https://example.com")
    task.logs.append(TaskLog(step_number=1, action="goto", result=StepResult.SUCCESS))

    restored = Task.from_dict(to_jsonable(task))

    assert restored.task_id == task.task_id
    assert restored.task_type is TaskType.BLACKBOX
    assert restored.logs[0].result is StepResult.SUCCESS


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        pytest.param("false", False, id="false_string"),
        pytest.param("0", False, id="zero_string"),
        pytest.param("true", True, id="true_string"),
        pytest.param(False, False, id="bool_false"),
        pytest.param(True, True, id="bool_true"),
    ],
)
def test_task_from_dict_parses_capture_screenshots_bool(raw_value, expected):
    task = Task.from_dict({"goal": "截图配置", "capture_screenshots": raw_value})

    assert task.capture_screenshots is expected


def test_task_from_dict_uses_default_capture_screenshots():
    task = Task.from_dict({"goal": "截图默认值"})

    assert task.capture_screenshots is True


@pytest.mark.parametrize(
    ("field", "raw_value", "expected"),
    [
        pytest.param("enabled", "false", False, id="enabled_false_string"),
        pytest.param("enabled", "0", False, id="enabled_zero_string"),
        pytest.param("enabled", "true", True, id="enabled_true_string"),
        pytest.param("is_default", "false", False, id="default_false_string"),
        pytest.param("is_default", "1", True, id="default_one_string"),
    ],
)
def test_model_config_from_dict_parses_bool_fields(field, raw_value, expected):
    data = {"name": "模型配置", field: raw_value}

    config = ModelConfig.from_dict(data)

    assert getattr(config, field) is expected


def test_model_config_from_dict_uses_bool_defaults():
    config = ModelConfig.from_dict({"name": "模型配置"})

    assert config.enabled is True
    assert config.is_default is False


def test_task_service_can_save_and_query_history(tmp_path):
    storage = TaskFileStorage(tmp_path)
    lifecycle = TaskLifecycleService(storage, event_publisher=None)
    log = TaskLogService(storage, event_publisher=None)
    reader = TaskReadService(storage)
    task = lifecycle.create_task(goal="打开页面", start_url="https://example.com")

    log.append_log(task, action="goto", url_after="https://example.com")
    log.append_finding(task.task_id, title="观察项", description="页面可访问")
    loaded = reader.get_task(task.task_id)

    assert loaded.current_step == 1
    assert len(loaded.findings) == 1
    assert reader.list_tasks(status=TaskStatus.PENDING)[0].task_id == task.task_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "has_handler",
    [True, False],
    ids=["with_handler", "without_handler"],
)
async def test_task_runner(tmp_path, has_handler):
    storage = TaskFileStorage(tmp_path / "tasks")
    lifecycle = TaskLifecycleService(storage, event_publisher=None)
    log = TaskLogService(storage, event_publisher=None)
    reader = TaskReadService(storage)
    task = lifecycle.create_task(
        goal="测试运行器",
        task_type=TaskType.BLACKBOX if has_handler else TaskType.WHITEBOX,
    )
    handlers = {}
    if has_handler:

        async def handler(running_task: Task) -> Task:
            return log.append_log(running_task, action="noop")

        handlers[TaskType.BLACKBOX] = handler

    runner = TaskRunner(
        lifecycle=lifecycle,
        reader=reader,
        handlers=handlers,
        report_generator=ReportGenerator(tmp_path / "reports"),
    )

    if has_handler:
        completed = await runner.run(task)
        assert completed.status is TaskStatus.COMPLETED
        assert completed.current_step == 1
        assert completed.report_path is not None
    else:
        with pytest.raises(TaskError):
            await runner.run(task)
        loaded = reader.get_task(task.task_id)
        assert loaded.status is TaskStatus.FAILED
        assert loaded.report_path is not None
