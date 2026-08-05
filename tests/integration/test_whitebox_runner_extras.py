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
    WhiteboxVisibilityError,
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

    # 稳定错误码持久化到 analysis_runs.failure_code（不再落通用 ANALYSIS_FAILED）
    runs, _ = app_stack.lifecycle.storage.list_analysis_runs(task.task_id)
    assert len(runs) == 1
    assert runs[0].failure_code == "WHITEBOX_REMOTE_JOB_FAILED"


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

    runs, _ = app_stack.lifecycle.storage.list_analysis_runs(task.task_id)
    assert len(runs) == 1
    assert runs[0].run_status == "CANCELLED"
    assert runs[0].failure_code == "WHITEBOX_TASK_CANCELLED"


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

    runs, _ = app_stack.lifecycle.storage.list_analysis_runs(task.task_id)
    assert len(runs) == 1
    assert runs[0].run_status == "TIMED_OUT"
    assert runs[0].failure_code == "WHITEBOX_TASK_TIMEOUT"


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


@pytest.mark.asyncio
async def test_git_source_snapshot_id_uses_commit_sha(app_stack, tmp_path) -> None:
    """git 源 source_snapshot_id 使用克隆 HEAD commit SHA（跨运行稳定），不再退化为 analysis_id。"""
    client = _make_mock_client()
    client.submit_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="PENDING")
    client.get_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status="SUCCEEDED")
    client.get_analyze_job_result.return_value = WhiteboxResult(call_graph=CallGraph(nodes={}))

    # git 源：content_sha256=None，resolved_commit_sha 为权威快照标识
    resolver = MagicMock(spec=SourceResolver)
    resolver.resolve.return_value = ResolvedSource(
        source_type="git",
        resolved_path=str(tmp_path),
        requested_ref="main",
        resolved_commit_sha="deadbeef" * 5,
        ref_type="branch",
        is_dirty=False,
        content_sha256=None,
        managed_snapshot=True,
    )

    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="test",
        parameters={"repo_url": "https://example.com/repo.git", "ref": "main", "scope": "all"},
        timeout_seconds=_LONG_TIMEOUT,
    )
    app_stack.lifecycle.save_task(task)

    runner = WhiteboxRunner(
        client=client,
        source_resolver=resolver,
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
        poll_interval=0,
    )
    await runner.run(task)

    run = app_stack.lifecycle.storage.get_analysis_run(_latest_analysis_id(app_stack, task.task_id))
    assert run.source_snapshot_id == "deadbeef" * 5
    assert run.resolved_commit_sha == "deadbeef" * 5


def _latest_analysis_id(app_stack, task_id: str) -> str:
    """通过应用服务读取最新 analysis_id（list_analysis_runs 只用于取 ID）。"""
    runs, _ = app_stack.lifecycle.storage.list_analysis_runs(task_id)
    assert runs, "应至少存在一条分析记录"
    return runs[0].analysis_id


@pytest.mark.asyncio
async def test_visibility_failure_persists_error_code(app_stack, tmp_path) -> None:
    """容器路径可见性校验失败 → WhiteboxVisibilityError，错误码持久化到 analysis_runs。"""
    client = _make_mock_client()
    client.validate_source.return_value = SourceVisibilityResult(
        status=VisibilityStatus.ENDPOINT_UNSUPPORTED,
        exists=True,
        readable=True,
        reason="analyzer version too old",
    )

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

    with pytest.raises(WhiteboxVisibilityError):
        await runner.run(task)

    runs, _ = app_stack.lifecycle.storage.list_analysis_runs(task.task_id)
    assert len(runs) == 1
    assert runs[0].failure_code == "WHITEBOX_VISIBILITY_ERROR"
