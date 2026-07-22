from __future__ import annotations

import asyncio

import pytest
from argus_py.infra.queue import TaskQueue
from argus_py.infra.worker import TaskWorker


@pytest.mark.asyncio
async def test_stop_timeout_includes_full_queue_signal_delivery() -> None:
    queue = TaskQueue(max_size=1)
    await queue.enqueue("queued-task")
    worker = TaskWorker(queue=queue, lifecycle=None, reader=None)  # type: ignore[arg-type]
    blocker = asyncio.create_task(asyncio.Event().wait())
    worker._tasks = [blocker]  # type: ignore[list-item]
    worker._started = True

    loop = asyncio.get_running_loop()
    started = loop.time()
    await worker.stop(timeout_seconds=0.02)

    assert loop.time() - started < 0.5
    assert blocker.cancelled()
    assert worker.is_started is False
