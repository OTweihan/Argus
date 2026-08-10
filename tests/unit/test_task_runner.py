"""TaskRunner 生命周期与 handler 返回值语义回归测试（O-06）。

覆盖四类场景：
1. handler 返回全新 Task 快照 → 结果字段进入报告与最终持久化结果；
2. handler 返回 None → 以原地修改的 task 对象为准（Whitebox 现状保持）；
3. 外部取消写入终态 → 迟到的成功返回不能覆盖；
4. handler 自身已写终态 → runner 不再推进。
外加外部 pause 与 async-only 收窄的守卫用例。
"""

import pytest
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.execution.runner import TaskRunner
from argus_py.report.generator import ReportGenerator
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.models import Finding, Task
from argus_py.task.storage import TaskFileStorage


def _make_runner(tmp_path, lifecycle, handler) -> TaskRunner:
    """构造使用 TaskFileStorage 的 TaskRunner。"""
    return TaskRunner(
        lifecycle=lifecycle,
        handlers={TaskType.BLACKBOX: handler},
        report_generator=ReportGenerator(tmp_path / "reports"),
    )


def _make_task(lifecycle: TaskLifecycleService) -> Task:
    return lifecycle.create_task(goal="运行器", task_type=TaskType.BLACKBOX)


@pytest.mark.asyncio
async def test_handler_returns_fresh_task_snapshot(tmp_path):
    """handler 返回全新 Task 快照：result_summary/findings 进入报告与终态。"""
    storage = TaskFileStorage(tmp_path / "tasks")
    lifecycle = TaskLifecycleService(storage, event_publisher=None)
    task = _make_task(lifecycle)

    async def handler(running_task: Task) -> Task:
        fresh = Task(
            goal=running_task.goal,
            task_id=running_task.task_id,
            task_type=running_task.task_type,
            result_summary="handler 返回的摘要",
        )
        fresh.findings.append(Finding(title="新发现", description="来自返回快照"))
        return fresh

    runner = _make_runner(tmp_path, lifecycle, handler)
    completed = await runner.run(task)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.task_id == task.task_id
    assert completed.result_summary == "handler 返回的摘要"
    assert [f.title for f in completed.findings] == ["新发现"]
    # 生命周期字段未被全新快照的默认值破坏
    assert completed.started_at is not None
    assert completed.report_path is not None

    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.COMPLETED
    assert loaded.result_summary == "handler 返回的摘要"
    assert [f.title for f in loaded.findings] == ["新发现"]
    assert loaded.report_path is not None


@pytest.mark.asyncio
async def test_handler_returns_none_keeps_inplace_mutations(tmp_path):
    """handler 返回 None：以原地修改的 task 对象为准，不丢失未持久化修改。"""
    storage = TaskFileStorage(tmp_path / "tasks")
    lifecycle = TaskLifecycleService(storage, event_publisher=None)
    task = _make_task(lifecycle)

    async def handler(running_task: Task) -> None:
        # 只原地修改、不逐字段持久化，验证 None 路径不会丢失内存态修改
        running_task.result_summary = "原地写入的摘要"
        return None

    runner = _make_runner(tmp_path, lifecycle, handler)
    completed = await runner.run(task)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.result_summary == "原地写入的摘要"
    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.COMPLETED
    assert loaded.result_summary == "原地写入的摘要"


@pytest.mark.asyncio
async def test_external_cancel_not_overwritten_by_late_success(tmp_path):
    """外部取消写入终态后，迟到的成功返回不能覆盖 CANCELLED。"""
    storage = TaskFileStorage(tmp_path / "tasks")
    lifecycle = TaskLifecycleService(storage, event_publisher=None)
    task = _make_task(lifecycle)

    async def handler(running_task: Task) -> Task:
        # 模拟外部 API 取消：已持久化 CANCELLED
        lifecycle.cancel_task(running_task.task_id)
        fresh = Task(
            goal=running_task.goal,
            task_id=running_task.task_id,
            result_summary="迟到的成功",
        )
        return fresh

    runner = _make_runner(tmp_path, lifecycle, handler)
    completed = await runner.run(task)

    assert completed.status is TaskStatus.CANCELLED
    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.CANCELLED
    assert loaded.result_summary is None  # 迟到成功未被采纳


@pytest.mark.asyncio
async def test_external_pause_not_overwritten(tmp_path):
    """外部 pause 写入 PAUSED 后，runner 不推进完成。"""
    storage = TaskFileStorage(tmp_path / "tasks")
    lifecycle = TaskLifecycleService(storage, event_publisher=None)
    task = _make_task(lifecycle)

    async def handler(running_task: Task) -> Task:
        lifecycle.pause_task(running_task.task_id)
        return Task(
            goal=running_task.goal,
            task_id=running_task.task_id,
            result_summary="pause 后返回",
        )

    runner = _make_runner(tmp_path, lifecycle, handler)
    completed = await runner.run(task)

    assert completed.status is TaskStatus.PAUSED
    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.PAUSED
    assert loaded.result_summary is None


@pytest.mark.asyncio
async def test_handler_persisted_terminal_state_not_overwritten(tmp_path):
    """handler 自身已写入终态（FAILED）：runner 不再推进为 COMPLETED。"""
    storage = TaskFileStorage(tmp_path / "tasks")
    lifecycle = TaskLifecycleService(storage, event_publisher=None)
    task = _make_task(lifecycle)

    async def handler(running_task: Task) -> Task:
        return lifecycle.fail_task(running_task, "handler 内部失败")

    runner = _make_runner(tmp_path, lifecycle, handler)
    completed = await runner.run(task)

    assert completed.status is TaskStatus.FAILED
    assert completed.error_message == "handler 内部失败"
    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.FAILED
    assert loaded.error_message == "handler 内部失败"


@pytest.mark.asyncio
async def test_sync_handler_rejected(tmp_path):
    """TaskHandler 收窄为 async-only：同步 handler 被拦截并明确报错。"""
    storage = TaskFileStorage(tmp_path / "tasks")
    lifecycle = TaskLifecycleService(storage, event_publisher=None)
    task = _make_task(lifecycle)

    def sync_handler(running_task: Task) -> Task:
        running_task.result_summary = "同步写入"
        return running_task

    runner = _make_runner(tmp_path, lifecycle, sync_handler)
    with pytest.raises(TaskError, match="必须是异步 handler"):
        await runner.run(task)
    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.FAILED
    assert "必须是异步 handler" in (loaded.error_message or "")
