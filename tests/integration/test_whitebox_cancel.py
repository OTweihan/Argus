"""O-04 白盒协作取消集成测试：确认/不可达/超时/Worker shutdown 远端取消。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from argus_py.core.enums import TaskType
from argus_py.whitebox.client import (
    SourceVisibilityResult,
    VisibilityStatus,
    WhiteboxClient,
    WhiteboxTransientError,
)
from argus_py.whitebox.exceptions import WhiteboxTaskCancelled, WhiteboxTaskTimeout
from argus_py.whitebox.models import WhiteboxJobStatus
from argus_py.whitebox.runner import WhiteboxRunner
from argus_py.whitebox.source_resolver import ResolvedSource, SourceResolver


def _make_mock_client() -> AsyncMock:
    client = AsyncMock(spec=WhiteboxClient)
    client.request_timeout = 30.0
    client.validate_source.return_value = SourceVisibilityResult(
        status=VisibilityStatus.VALIDATED, exists=True, readable=True
    )
    return client


def _make_resolver(fake_path: str) -> MagicMock:
    resolver = MagicMock(spec=SourceResolver)
    resolver.resolve_path.return_value = ResolvedSource(
        source_type="local",
        resolved_path=fake_path,
        requested_ref=None,
        resolved_commit_sha="abc123",
        ref_type=None,
        is_dirty=False,
        managed_snapshot=True,
    )
    return resolver


def _make_task(tmp_path, timeout_seconds: int = 999):
    from argus_py.task.models import Task

    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="白盒分析",
        parameters={"source_path": str(tmp_path)},
        timeout_seconds=timeout_seconds,
    )
    return task


def _make_runner(app_stack, client, resolver) -> WhiteboxRunner:
    return WhiteboxRunner(
        client=client,
        source_resolver=resolver,
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
        poll_interval=0,
        cancel_confirmation_timeout=0.0,
    )


@pytest.mark.asyncio
async def test_local_cancel_confirmed_remote_marks_cancelled(app_stack, tmp_path) -> None:
    """Java 确认取消 → origin=remote，analysis_runs 落 CANCELLED。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    client.cancel_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="CANCELLED")

    task = _make_task(tmp_path)
    app_stack.lifecycle.save_task(task)
    app_stack.lifecycle.get_cancellation_token(task.task_id).cancel()

    with pytest.raises(WhiteboxTaskCancelled) as excinfo:
        await _make_runner(app_stack, client, _make_resolver(str(tmp_path))).run(task)

    assert excinfo.value.origin == "remote"
    client.cancel_analyze_job.assert_awaited_once_with("j1")

    runs, _ = app_stack.lifecycle.storage.list_analysis_runs(task.task_id)
    assert runs[0].run_status == "CANCELLED"


@pytest.mark.asyncio
async def test_local_cancel_unreachable_keeps_stopped_waiting(app_stack, tmp_path) -> None:
    """无法联系远端 → origin=local，保留 STOPPED_WAITING 语义。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    client.cancel_analyze_job.side_effect = WhiteboxTransientError("java down")

    task = _make_task(tmp_path)
    app_stack.lifecycle.save_task(task)
    app_stack.lifecycle.get_cancellation_token(task.task_id).cancel()

    with pytest.raises(WhiteboxTaskCancelled) as excinfo:
        await _make_runner(app_stack, client, _make_resolver(str(tmp_path))).run(task)

    assert excinfo.value.origin == "local"

    runs, _ = app_stack.lifecycle.storage.list_analysis_runs(task.task_id)
    assert runs[0].run_status == "STOPPED_WAITING"


@pytest.mark.asyncio
async def test_local_cancel_404_unknown_keeps_stopped_waiting(app_stack, tmp_path) -> None:
    """404（作业过期 / 旧版 Java 无端点）→ 不能判定已取消，保留 STOPPED_WAITING。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    client.cancel_analyze_job.return_value = None

    task = _make_task(tmp_path)
    app_stack.lifecycle.save_task(task)
    app_stack.lifecycle.get_cancellation_token(task.task_id).cancel()

    with pytest.raises(WhiteboxTaskCancelled) as excinfo:
        await _make_runner(app_stack, client, _make_resolver(str(tmp_path))).run(task)

    assert excinfo.value.origin == "local"

    runs, _ = app_stack.lifecycle.storage.list_analysis_runs(task.task_id)
    assert runs[0].run_status == "STOPPED_WAITING"


@pytest.mark.asyncio
async def test_timeout_best_effort_cancels_remote(app_stack, tmp_path) -> None:
    """Python deadline 到达 → best-effort 通知远端后抛超时。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    # 永远 RUNNING，直到本地 deadline 触发
    client.get_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="RUNNING")

    task = _make_task(tmp_path, timeout_seconds=1)
    app_stack.lifecycle.save_task(task)

    with pytest.raises(WhiteboxTaskTimeout):
        await _make_runner(app_stack, client, _make_resolver(str(tmp_path))).run(task)

    client.cancel_analyze_job.assert_awaited_once_with("j1")

    runs, _ = app_stack.lifecycle.storage.list_analysis_runs(task.task_id)
    assert runs[0].run_status == "TIMED_OUT"


@pytest.mark.asyncio
async def test_worker_shutdown_cancels_remote_job(app_stack, tmp_path) -> None:
    """Worker shutdown（CancelledError）→ best-effort 通知远端取消。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    gate = asyncio.Event()

    async def blocking_get(job_id: str, timeout: float | None = None) -> WhiteboxJobStatus:
        await gate.wait()
        return WhiteboxJobStatus(job_id=job_id, status="RUNNING")

    client.get_analyze_job.side_effect = blocking_get
    client.cancel_analyze_job = AsyncMock(
        return_value=WhiteboxJobStatus(job_id="j1", status="CANCELLED")
    )

    task = _make_task(tmp_path)
    app_stack.lifecycle.save_task(task)

    runner = _make_runner(app_stack, client, _make_resolver(str(tmp_path)))
    rtask = asyncio.create_task(runner.run(task))
    await asyncio.sleep(0.05)  # 让轮询进入 get_analyze_job 阻塞点
    rtask.cancel()
    with pytest.raises(asyncio.CancelledError):
        await rtask

    client.cancel_analyze_job.assert_awaited_once_with("j1")
