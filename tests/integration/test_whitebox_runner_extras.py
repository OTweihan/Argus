"""阶段四：WhiteboxRunner 高层状态机补充测试。

扩展 tests/integration/test_whitebox_runner.py，覆盖
终态/取消/超时/transient error 等状态机路径。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from argus_py.core.enums import TaskType
from argus_py.task.models import Task
from argus_py.whitebox.client import (
    SourceVisibilityResult,
    VisibilityStatus,
    WhiteboxClient,
    WhiteboxJobNotFoundError,
    WhiteboxTransientError,
)
from argus_py.whitebox.exceptions import (
    WhiteboxRemoteJobFailed,
    WhiteboxTaskCancelled,
    WhiteboxTaskError,
    WhiteboxTaskTimeout,
)
from argus_py.whitebox.models import (
    CallGraph,
    WhiteboxJobStatus,
    WhiteboxResult,
)
from argus_py.whitebox.runner import WhiteboxRunner
from argus_py.whitebox.source_resolver import ResolvedSource, SourceResolver

# 用于 transient error / 取消测试的长 timeout，确保 _poll 循环有时间进入终态
_LONG_TIMEOUT = 999


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
    )
    return resolver


# ── 终态 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_failed_raises_remote_job_failed(app_stack, tmp_path) -> None:
    """FAILED 终态 → WhiteboxRemoteJobFailed。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    client.get_analyze_job.return_value = WhiteboxJobStatus(
        job_id="j1", status="FAILED", error="analysis error"
    )

    task = Task(task_type=TaskType.WHITEBOX, goal="test", parameters={"source_path": str(tmp_path)})
    app_stack.lifecycle.save_task(task)

    runner = WhiteboxRunner(
        client=client,
        source_resolver=_make_resolver(str(tmp_path)),
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
        poll_interval=0,
    )

    with pytest.raises(WhiteboxRemoteJobFailed, match="j1"):
        await runner.run(task)


@pytest.mark.asyncio
async def test_job_cancelled_remote(app_stack, tmp_path) -> None:
    """CANCELLED 终态 → WhiteboxTaskCancelled(origin="remote")。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    client.get_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="CANCELLED")

    task = Task(task_type=TaskType.WHITEBOX, goal="test", parameters={"source_path": str(tmp_path)})
    app_stack.lifecycle.save_task(task)

    runner = WhiteboxRunner(
        client=client,
        source_resolver=_make_resolver(str(tmp_path)),
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
        poll_interval=0,
    )

    with pytest.raises(WhiteboxTaskCancelled):
        await runner.run(task)


@pytest.mark.asyncio
async def test_job_timed_out(app_stack, tmp_path) -> None:
    """TIMED_OUT 终态 → WhiteboxTaskTimeout。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    client.get_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="TIMED_OUT")

    task = Task(task_type=TaskType.WHITEBOX, goal="test", parameters={"source_path": str(tmp_path)})
    app_stack.lifecycle.save_task(task)

    runner = WhiteboxRunner(
        client=client,
        source_resolver=_make_resolver(str(tmp_path)),
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
        poll_interval=0,
    )

    with pytest.raises(WhiteboxTaskTimeout):
        await runner.run(task)


@pytest.mark.asyncio
async def test_job_expired(app_stack, tmp_path) -> None:
    """EXPIRED 终态 → WhiteboxRemoteJobFailed。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    client.get_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="EXPIRED")

    task = Task(task_type=TaskType.WHITEBOX, goal="test", parameters={"source_path": str(tmp_path)})
    app_stack.lifecycle.save_task(task)

    runner = WhiteboxRunner(
        client=client,
        source_resolver=_make_resolver(str(tmp_path)),
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
        poll_interval=0,
    )

    with pytest.raises(WhiteboxRemoteJobFailed, match="EXPIRED|过期"):
        await runner.run(task)


# ── transient error ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_three_consecutive_transient_errors(app_stack, tmp_path) -> None:
    """连续 3 次 transient error → WhiteboxTaskError。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    client.get_analyze_job.side_effect = WhiteboxTransientError("transient")

    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="test",
        parameters={"source_path": str(tmp_path)},
        timeout_seconds=_LONG_TIMEOUT,
    )
    app_stack.lifecycle.save_task(task)

    runner = WhiteboxRunner(
        client=client,
        source_resolver=_make_resolver(str(tmp_path)),
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
        poll_interval=0,
        max_poll_interval=1,
    )

    with pytest.raises(WhiteboxTaskError, match="瞬时失败"):
        await runner.run(task)


@pytest.mark.asyncio
async def test_transient_error_then_success(app_stack, tmp_path) -> None:
    """1 次 transient error 后成功 → 正常完成。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    # 第 1 次 transient，第 2 次 SUCCEEDED
    client.get_analyze_job.side_effect = [
        WhiteboxTransientError("transient"),
        WhiteboxJobStatus(job_id="j1", status="SUCCEEDED"),
    ]
    client.get_analyze_job_result.return_value = WhiteboxResult(call_graph=CallGraph(nodes={}))

    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="test",
        parameters={"source_path": str(tmp_path)},
        timeout_seconds=_LONG_TIMEOUT,
    )
    app_stack.lifecycle.save_task(task)

    runner = WhiteboxRunner(
        client=client,
        source_resolver=_make_resolver(str(tmp_path)),
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
        poll_interval=0,
    )

    await runner.run(task)
    # 没有抛异常
    assert task.result_summary is not None


@pytest.mark.asyncio
async def test_job_not_found(app_stack, tmp_path) -> None:
    """WhiteboxJobNotFoundError → WhiteboxTaskError。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    client.get_analyze_job.side_effect = WhiteboxJobNotFoundError("not found")

    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="test",
        parameters={"source_path": str(tmp_path)},
        timeout_seconds=_LONG_TIMEOUT,
    )
    app_stack.lifecycle.save_task(task)

    runner = WhiteboxRunner(
        client=client,
        source_resolver=_make_resolver(str(tmp_path)),
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
        poll_interval=0,
    )

    with pytest.raises(WhiteboxTaskError, match="不存在"):
        await runner.run(task)


# ── 取消 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_remote_job_is_noop(app_stack, tmp_path) -> None:
    """_cancel_remote_job 返回 False 且不发送 HTTP 请求。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    client.get_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="SUCCEEDED")
    client.get_analyze_job_result.return_value = WhiteboxResult(call_graph=CallGraph(nodes={}))

    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="test",
        parameters={"source_path": str(tmp_path)},
        timeout_seconds=_LONG_TIMEOUT,
    )
    app_stack.lifecycle.save_task(task)

    runner = WhiteboxRunner(
        client=client,
        source_resolver=_make_resolver(str(tmp_path)),
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
        poll_interval=0,
    )

    cancelled = await runner._cancel_remote_job("j1")
    assert cancelled is False
    client.cancel_job.assert_not_called()
