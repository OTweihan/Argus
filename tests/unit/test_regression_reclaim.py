"""回归批次回收路径：leave_running 与 snapshot→running 竞态。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from argus_py.core.enums import TaskStatus
from argus_py.regression.application import RegressionService
from argus_py.regression.enums import RegressionItemStatus
from argus_py.task.storage import TaskSQLiteStorage


@dataclass
class _Item:
    item_id: str
    task_id: str | None = None


class _RaceQueue:
    """模拟：snapshot 时 queued，cancel_many 后升为 running。"""

    def __init__(self, *, snapshot: dict[str, str], live_after_cancel: dict[str, str]) -> None:
        self._snapshot = dict(snapshot)
        self._live = dict(live_after_cancel)
        self.cancel_many_calls: list[list[str]] = []

    async def snapshot_statuses(self) -> dict[str, str]:
        return dict(self._snapshot)

    async def cancel_many(self, task_ids: list[str] | tuple[str, ...] | set[str]) -> int:
        self.cancel_many_calls.append(list(task_ids))
        # cancel 之后状态切到 live 视图（模拟 worker 已取走）
        return 0

    async def scheduler_status(self, task_id: str) -> str | None:
        return self._live.get(task_id)


@pytest.mark.asyncio
async def test_reclaim_leave_running_rechecks_live_after_queued_snapshot(
    tmp_path: Path,
) -> None:
    """snapshot=queued 但 cancel 后已 running 时，不得 cancel_task。"""
    storage = TaskSQLiteStorage(tmp_path / "argus.db")
    lifecycle = MagicMock()
    lifecycle.storage = storage
    lifecycle.cancel_task = MagicMock(side_effect=AssertionError("不应 cancel running 子任务"))

    # headers：pending，若误入 cancel 分支会触发上面的 AssertionError
    storage.create_task = MagicMock()  # type: ignore[method-assign]
    lifecycle.storage.load_task_headers = MagicMock(  # type: ignore[method-assign]
        return_value={
            "t-race": {"task_id": "t-race", "status": TaskStatus.PENDING.value},
            "t-queued": {"task_id": "t-queued", "status": TaskStatus.PENDING.value},
        }
    )

    queue = _RaceQueue(
        snapshot={"t-race": "queued", "t-queued": "queued"},
        live_after_cancel={"t-race": "running"},  # t-queued 已不在队列 → None
    )

    service = RegressionService(
        storage=storage,
        lifecycle=lifecycle,
        queue=queue,  # type: ignore[arg-type]
        resolve_create_params=lambda **kwargs: {},
        event_publisher=None,
    )

    item_race = _Item("item-race", "t-race")
    item_queued = _Item("item-queued", "t-queued")
    # cancel_task 仅允许 t-queued
    cancelled: list[str] = []

    def _cancel(task_id: str) -> None:
        cancelled.append(task_id)

    lifecycle.cancel_task = _cancel

    updates = await service._reclaim_submitted_tasks(  # noqa: SLF001
        [(item_race, "t-race"), (item_queued, "t-queued")],
        running_item_error_code="BATCH_ABORTED_TASK_RUNNING",
        cancelled_item_error_code="BATCH_QUEUE_FULL",
        leave_running_tasks=True,
    )

    assert cancelled == ["t-queued"]
    by_item = {u["item_id"]: u for u in updates}
    assert by_item["item-race"]["error_code"] == "BATCH_ABORTED_TASK_RUNNING"
    assert "继续执行" in (by_item["item-race"].get("error_message") or "")
    assert by_item["item-queued"]["error_code"] == "BATCH_QUEUE_FULL"
    assert by_item["item-queued"].get("error_message") is None


@pytest.mark.asyncio
async def test_reclaim_leave_running_skips_snapshot_running(tmp_path: Path) -> None:
    """snapshot 已是 running：直接镜像，不查 live、不 cancel。"""
    storage = TaskSQLiteStorage(tmp_path / "argus.db")
    lifecycle = MagicMock()
    lifecycle.storage = storage
    lifecycle.storage.load_task_headers = MagicMock(return_value={})  # type: ignore[method-assign]
    lifecycle.cancel_task = MagicMock(side_effect=AssertionError("snapshot running 不应 cancel"))

    queue = MagicMock()
    queue.snapshot_statuses = AsyncMock(return_value={"t-run": "running"})
    queue.cancel_many = AsyncMock(return_value=0)
    queue.scheduler_status = AsyncMock(side_effect=AssertionError("不应 live 查询"))

    service = RegressionService(
        storage=storage,
        lifecycle=lifecycle,
        queue=queue,
        resolve_create_params=lambda **kwargs: {},
        event_publisher=None,
    )
    updates = await service._reclaim_submitted_tasks(  # noqa: SLF001
        [(_Item("item-1", "t-run"), "t-run")],
        running_item_error_code="BATCH_ABORTED_TASK_RUNNING",
        cancelled_item_error_code="BATCH_QUEUE_FULL",
        leave_running_tasks=True,
    )
    assert len(updates) == 1
    assert updates[0]["error_code"] == "BATCH_ABORTED_TASK_RUNNING"
    queue.cancel_many.assert_not_called()


@pytest.mark.asyncio
async def test_reclaim_user_cancel_still_cancels_running(tmp_path: Path) -> None:
    """leave_running=False：running 也要 cancel_task，并预取消 token。"""
    storage = TaskSQLiteStorage(tmp_path / "argus.db")
    lifecycle = MagicMock()
    lifecycle.storage = storage
    lifecycle.storage.load_task_headers = MagicMock(  # type: ignore[method-assign]
        return_value={"t-run": {"task_id": "t-run", "status": TaskStatus.RUNNING.value}}
    )
    token = MagicMock()
    lifecycle.get_cancellation_token = MagicMock(return_value=token)
    cancelled: list[Any] = []
    lifecycle.cancel_task = MagicMock(side_effect=lambda tid: cancelled.append(tid))

    queue = MagicMock()
    queue.snapshot_statuses = AsyncMock(return_value={"t-run": "running"})
    queue.cancel_many = AsyncMock(return_value=0)
    queue.scheduler_status = AsyncMock(
        side_effect=AssertionError("用户取消不需要 leave live 再确认")
    )

    service = RegressionService(
        storage=storage,
        lifecycle=lifecycle,
        queue=queue,
        resolve_create_params=lambda **kwargs: {},
        event_publisher=None,
    )
    updates = await service._reclaim_submitted_tasks(  # noqa: SLF001
        [(_Item("item-1", "t-run"), "t-run")],
        running_item_error_code="BATCH_CANCELLED",
        cancelled_item_error_code="BATCH_CANCELLED",
        leave_running_tasks=False,
    )
    token.cancel.assert_called_once()
    assert cancelled == ["t-run"]
    assert updates[0]["error_code"] == "BATCH_CANCELLED"
    assert updates[0]["status"] == RegressionItemStatus.CANCELLED
