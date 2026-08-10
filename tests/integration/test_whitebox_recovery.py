"""O-04 启动恢复集成测试：孤儿白盒作业的重新接管。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.task.models import Task
from argus_py.whitebox.client import WhiteboxClient, WhiteboxTransientError
from argus_py.whitebox.models import CallGraph, WhiteboxJobStatus, WhiteboxResult
from argus_py.whitebox.recovery import reconcile_orphan_whitebox_jobs


def _lease_expired_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()


def _make_stale_task(app_stack, tmp_path, *, job_id: str, with_run: bool = True) -> Task:
    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="白盒分析",
        parameters={"source_path": str(tmp_path)},
        timeout_seconds=999,
    )
    app_stack.lifecycle.save_task(task)
    app_stack.lifecycle.storage.update_task(
        task.task_id,
        status=TaskStatus.RUNNING.value,
        worker_id="dead-worker",
        worker_lease_expires_at=_lease_expired_iso(),
        external_job_id=job_id,
        external_job_status="PENDING",
    )
    if with_run:
        app_stack.lifecycle.create_analysis_run(
            analysis_id=f"run-{task.task_id}",
            task_id=task.task_id,
            source_snapshot_id="snap",
            config_json=task.whitebox_config_json or "{}",
        )
    return task


def _make_client(status: str | Exception) -> Any:
    client = AsyncMock(spec=WhiteboxClient)
    if isinstance(status, Exception):
        client.get_analyze_job.side_effect = status
    else:
        client.get_analyze_job.return_value = WhiteboxJobStatus(job_id="j1", status=status)
    client.get_analyze_job_result.return_value = WhiteboxResult(
        endpoints=[],
        call_graph=CallGraph(nodes={}),
        findings=[],
        execution_flows=[],
        clusters=[],
        diagnostics=None,
    )
    return client


async def _reconcile(app_stack, client: WhiteboxClient) -> None:
    await reconcile_orphan_whitebox_jobs(
        storage=app_stack.lifecycle.storage,
        lifecycle=app_stack.lifecycle,
        queue=app_stack.queue,
        client=client,
    )


@pytest.mark.asyncio
async def test_recovery_adopts_succeeded_result(app_stack, tmp_path) -> None:
    """远端 SUCCEEDED → 拉取结果，任务落 COMPLETED。"""
    task = _make_stale_task(app_stack, tmp_path, job_id="j1")
    client = _make_client("SUCCEEDED")

    await _reconcile(app_stack, client)

    latest = app_stack.lifecycle.storage.load(task.task_id)
    assert latest.status == TaskStatus.COMPLETED
    assert latest.result_summary is not None
    client.get_analyze_job_result.assert_awaited_once_with("j1", timeout=15.0)
    runs, _ = app_stack.lifecycle.storage.list_analysis_runs(task.task_id)
    assert runs[0].run_status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_recovery_requeues_running_job(app_stack, tmp_path) -> None:
    """远端 RUNNING → 任务重置 PENDING 重新入队（幂等复用远端 job）。"""
    task = _make_stale_task(app_stack, tmp_path, job_id="j1")
    client = _make_client("RUNNING")

    await _reconcile(app_stack, client)

    latest = app_stack.lifecycle.storage.load(task.task_id)
    assert latest.status == TaskStatus.PENDING
    assert latest.worker_id is None
    assert latest.worker_lease_expires_at is None
    assert latest.external_job_status == "RUNNING"
    # 已重新入队
    assert task.task_id in app_stack.queue._queued_ids


@pytest.mark.asyncio
async def test_recovery_marks_cancelled_job_failed(app_stack, tmp_path) -> None:
    """远端 CANCELLED → 任务落 FAILED 并携带远端状态（不再静默孤儿）。"""
    task = _make_stale_task(app_stack, tmp_path, job_id="j1")
    client = _make_client("CANCELLED")

    await _reconcile(app_stack, client)

    latest = app_stack.lifecycle.storage.load(task.task_id)
    assert latest.status == TaskStatus.FAILED
    assert "CANCELLED" in (latest.error_message or "")


@pytest.mark.asyncio
async def test_recovery_marks_timed_out_job_timeout(app_stack, tmp_path) -> None:
    """远端 TIMED_OUT → 任务落 TIMEOUT。"""
    task = _make_stale_task(app_stack, tmp_path, job_id="j1")
    client = _make_client("TIMED_OUT")

    await _reconcile(app_stack, client)

    latest = app_stack.lifecycle.storage.load(task.task_id)
    assert latest.status == TaskStatus.TIMEOUT


@pytest.mark.asyncio
async def test_recovery_falls_back_to_failed_when_unreachable(app_stack, tmp_path) -> None:
    """远端不可达 → 任务落 FAILED（无法接管，不静默遗留）。"""
    task = _make_stale_task(app_stack, tmp_path, job_id="j1")
    client = _make_client(WhiteboxTransientError("java down"))

    await _reconcile(app_stack, client)

    latest = app_stack.lifecycle.storage.load(task.task_id)
    assert latest.status == TaskStatus.FAILED
    assert "UNREACHABLE" in (latest.error_message or "")


@pytest.mark.asyncio
async def test_recovery_requeue_preserves_lease_race_guard(app_stack, tmp_path) -> None:
    """CAS 保护：任务已被其他逻辑改状态时，重入队应被跳过。"""
    task = _make_stale_task(app_stack, tmp_path, job_id="j1")
    client = _make_client("RUNNING")
    # 先手动把任务改成已终态（模拟并发修改）
    app_stack.lifecycle.storage.update_task(
        task.task_id,
        status=TaskStatus.FAILED.value,
        error_message="并发已处理",
    )

    await _reconcile(app_stack, client)

    latest = app_stack.lifecycle.storage.load(task.task_id)
    assert latest.status == TaskStatus.FAILED
    assert latest.error_message == "并发已处理"
    assert task.task_id not in app_stack.queue._queued_ids
