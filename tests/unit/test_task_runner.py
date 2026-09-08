"""TaskRunner 生命周期与 handler 返回值语义回归测试（O-06）。

覆盖四类场景：
1. handler 返回全新 Task 快照 → result_summary 等行字段进入报告与 tasks 表落盘；
2. handler 返回 None → 以原地修改的 task 对象为准（Whitebox 现状保持）；
3. 外部取消写入终态 → 迟到的成功返回不能覆盖；
4. handler 自身已写终态 → runner 不再推进。
外加外部 pause、async-only 守卫，以及 findings 独立表正向持久化（save_task_findings）。

存储与生产对齐：一律 TaskSQLiteStorage（maintainability M1）。
findings 不在 complete_task/storage.save 路径写入，须经 lifecycle.save_task_findings
（白盒 runner 在 complete 前调用）；storage.load 会 join findings 表。
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.infra.events import EventBus
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.models import Finding, Task

from tests.helpers.factories import make_lifecycle, make_sqlite_storage, make_task_runner


def _make_task(lifecycle: TaskLifecycleService) -> Task:
    return lifecycle.create_task(goal="运行器", task_type=TaskType.BLACKBOX)


@pytest.mark.asyncio
async def test_handler_returns_fresh_task_snapshot(tmp_path):
    """handler 返回全新 Task 快照：result_summary 进入报告与 tasks 行落盘。

    SQLite 下 findings 在独立表：complete_task/storage.save 只写 tasks 行。
    内存中的 completed.findings 仍由 runner 采纳；行字段必须落盘。
    findings 表写入见 test_save_task_findings_persists_and_reloads。
    """
    storage, lifecycle = make_lifecycle(tmp_path)
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

    runner = make_task_runner(tmp_path, lifecycle, {TaskType.BLACKBOX: handler})
    completed = await runner.run(task)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.task_id == task.task_id
    assert completed.result_summary == "handler 返回的摘要"
    assert [f.title for f in completed.findings] == ["新发现"]
    assert completed.started_at is not None
    assert completed.report_path is not None

    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.COMPLETED
    assert loaded.result_summary == "handler 返回的摘要"
    assert loaded.report_path is not None
    # findings 表未由 complete_task 写入（与生产 SQLite 一致）
    assert loaded.findings == []


def test_save_task_findings_persists_and_reloads(tmp_path):
    """生产路径：save_task_findings 写入 findings 表，load 可 join 读回；同 analysis_id 幂等替换。

    findings.analysis_id 有 FK → analysis_runs，与白盒落盘前须先 create_analysis_run 一致。
    """
    storage, lifecycle = make_lifecycle(tmp_path)
    task = _make_task(lifecycle)
    analysis_id = "analysis-m1-findings"
    lifecycle.create_analysis_run(
        analysis_id,
        task.task_id,
        source_snapshot_id="snap-m1",
    )
    task.findings = [
        Finding(
            title="首发",
            description="第一批",
            analysis_id=analysis_id,
        ),
        Finding(
            title="次发",
            description="第一批第二条",
            analysis_id=analysis_id,
        ),
    ]
    lifecycle.save_task_findings(task)

    loaded = storage.load(task.task_id)
    assert sorted(f.title for f in loaded.findings) == ["次发", "首发"]
    assert all(f.analysis_id == analysis_id for f in loaded.findings)

    # 同 analysis_id 再写：先删后插，不累积
    task.findings = [
        Finding(
            title="替换后",
            description="第二批",
            analysis_id=analysis_id,
        )
    ]
    lifecycle.save_task_findings(task)
    reloaded = storage.load(task.task_id)
    assert [f.title for f in reloaded.findings] == ["替换后"]


def test_factory_sqlite_storage_survives_reopen(tmp_path):
    """factories 产出的 SQLite 库在重建 storage 后仍可读（save/load smoke）。"""
    storage, lifecycle = make_lifecycle(tmp_path)
    task = lifecycle.create_task(goal="工厂 smoke", task_type=TaskType.BLACKBOX)
    task_id = task.task_id

    reopened = make_sqlite_storage(tmp_path)
    loaded = reopened.load(task_id)
    assert loaded.goal == "工厂 smoke"
    assert loaded.task_id == task_id
    assert loaded.status is TaskStatus.PENDING
    assert storage.db_path == reopened.db_path


@pytest.mark.asyncio
async def test_handler_returns_none_keeps_inplace_mutations(tmp_path):
    """handler 返回 None：以原地修改的 task 对象为准，不丢失未持久化修改。"""
    storage, lifecycle = make_lifecycle(tmp_path)
    task = _make_task(lifecycle)

    async def handler(running_task: Task) -> None:
        running_task.result_summary = "原地写入的摘要"
        return None

    runner = make_task_runner(tmp_path, lifecycle, {TaskType.BLACKBOX: handler})
    completed = await runner.run(task)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.result_summary == "原地写入的摘要"
    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.COMPLETED
    assert loaded.result_summary == "原地写入的摘要"


@pytest.mark.asyncio
async def test_terminal_callback_runs_outside_event_loop_thread(tmp_path):
    """终态落盘及回归回调经 IO executor 执行，不阻塞事件循环线程。"""
    callback_threads: list[int] = []
    _storage, lifecycle = make_lifecycle(
        tmp_path,
        on_task_terminal=lambda _task_id, _status: callback_threads.append(threading.get_ident()),
    )
    task = _make_task(lifecycle)

    async def handler(_running_task: Task) -> None:
        return None

    runner = make_task_runner(tmp_path, lifecycle, {TaskType.BLACKBOX: handler})
    await runner.run(task)

    assert len(callback_threads) == 1
    assert callback_threads[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_lifecycle_events_from_io_thread_reach_live_subscriber(tmp_path):
    """Runner 在线程池落盘时，生命周期事件仍回投 EventBus 实时订阅。"""
    bus = EventBus(history_limit=20)
    bus.bind_loop(asyncio.get_running_loop())
    _storage, lifecycle = make_lifecycle(tmp_path, event_publisher=bus.publish)
    task = _make_task(lifecycle)

    async def handler(_running_task: Task) -> None:
        return None

    subscription = await bus.subscribe(task_id=task.task_id, replay=False)
    runner = make_task_runner(tmp_path, lifecycle, {TaskType.BLACKBOX: handler})
    await runner.run(task)

    events = []
    while not any(event.event_type == "task.complete" for event in events):
        events.append(await asyncio.wait_for(subscription.queue.get(), timeout=1))

    statuses = [event.data.get("status") for event in events if event.event_type == "task.status"]
    assert statuses == [TaskStatus.RUNNING.value, TaskStatus.COMPLETED.value]
    assert bus.dropped_no_loop_count == 0
    await subscription.close()


@pytest.mark.asyncio
async def test_external_cancel_not_overwritten_by_late_success(tmp_path):
    """外部取消写入终态后，迟到的成功返回不能覆盖 CANCELLED。"""
    storage, lifecycle = make_lifecycle(tmp_path)
    task = _make_task(lifecycle)

    async def handler(running_task: Task) -> Task:
        lifecycle.cancel_task(running_task.task_id)
        fresh = Task(
            goal=running_task.goal,
            task_id=running_task.task_id,
            result_summary="迟到的成功",
        )
        return fresh

    runner = make_task_runner(tmp_path, lifecycle, {TaskType.BLACKBOX: handler})
    completed = await runner.run(task)

    assert completed.status is TaskStatus.CANCELLED
    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.CANCELLED
    assert loaded.result_summary is None


@pytest.mark.asyncio
async def test_external_pause_not_overwritten(tmp_path):
    """外部 pause 写入 PAUSED 后，runner 不推进完成。"""
    storage, lifecycle = make_lifecycle(tmp_path)
    task = _make_task(lifecycle)

    async def handler(running_task: Task) -> Task:
        lifecycle.pause_task(running_task.task_id)
        return Task(
            goal=running_task.goal,
            task_id=running_task.task_id,
            result_summary="pause 后返回",
        )

    runner = make_task_runner(tmp_path, lifecycle, {TaskType.BLACKBOX: handler})
    completed = await runner.run(task)

    assert completed.status is TaskStatus.PAUSED
    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.PAUSED
    assert loaded.result_summary is None


@pytest.mark.asyncio
async def test_handler_persisted_terminal_state_not_overwritten(tmp_path):
    """handler 自身已写入终态（FAILED）：runner 不再推进为 COMPLETED。"""
    storage, lifecycle = make_lifecycle(tmp_path)
    task = _make_task(lifecycle)

    async def handler(running_task: Task) -> Task:
        return lifecycle.fail_task(running_task, "handler 内部失败")

    runner = make_task_runner(tmp_path, lifecycle, {TaskType.BLACKBOX: handler})
    completed = await runner.run(task)

    assert completed.status is TaskStatus.FAILED
    assert completed.error_message == "handler 内部失败"
    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.FAILED
    assert loaded.error_message == "handler 内部失败"


@pytest.mark.asyncio
async def test_sync_handler_rejected(tmp_path):
    """TaskHandler 收窄为 async-only：同步 handler 被拦截并明确报错。"""
    storage, lifecycle = make_lifecycle(tmp_path)
    task = _make_task(lifecycle)

    def sync_handler(running_task: Task) -> Task:
        running_task.result_summary = "同步写入"
        return running_task

    runner = make_task_runner(tmp_path, lifecycle, {TaskType.BLACKBOX: sync_handler})
    with pytest.raises(TaskError, match="必须是异步 handler"):
        await runner.run(task)
    loaded = storage.load(task.task_id)
    assert loaded.status is TaskStatus.FAILED
    assert "必须是异步 handler" in (loaded.error_message or "")
