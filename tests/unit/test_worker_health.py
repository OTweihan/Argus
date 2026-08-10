"""TaskWorker 健康快照测试（O-02）。

``TaskWorker.is_started`` 只是"已调用过 start()"，不能反映 loop 异常退出。
这里验证 ``health_snapshot()`` 暴露真实存活状态：loop 数、存活数、异常结束数、
最近消费时间，以及 done callback 对未处理异常与取消的区分。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
from argus_py.core.exceptions import TaskError
from argus_py.infra.queue import TaskQueue
from argus_py.infra.worker import TaskWorker


def _worker(
    queue: TaskQueue | None = None,
    concurrency: int = 1,
    reader: Any = None,
    lifecycle: Any = None,
) -> TaskWorker:
    """构造测试 Worker。lifecycle 用 Mock 使 reconcile 走"非 SQLite storage"早退。"""
    return TaskWorker(
        queue=queue if queue is not None else TaskQueue(),
        lifecycle=lifecycle if lifecycle is not None else Mock(),
        reader=reader,
        handlers={},
        concurrency=concurrency,
    )


class TestHealthSnapshotBasics:
    def test_before_start_all_zero(self) -> None:
        snap = _worker().health_snapshot()
        assert snap.is_started is False
        assert snap.total_loops == 0
        assert snap.alive_loops == 0
        assert snap.exited_loops == 0
        assert snap.crashed_loops == 0
        assert snap.last_consume_at is None
        assert snap.recent_crashes == ()

    @pytest.mark.asyncio
    async def test_after_start_counts_loops(self) -> None:
        worker = _worker(concurrency=3)
        await worker.start()
        snap = worker.health_snapshot()
        assert snap.is_started is True
        assert snap.total_loops == 3
        assert snap.alive_loops == 3
        assert snap.crashed_loops == 0
        await worker.stop()
        # 停止后全部 loop 结束，无异常退出。
        after = worker.health_snapshot()
        assert after.is_started is False
        assert after.alive_loops == 0
        assert after.crashed_loops == 0

    @pytest.mark.asyncio
    async def test_stop_when_start_failed_before_loops_created(self) -> None:
        """start() 在 reconciliation 阶段失败（未创建 loop）时，stop() 必须干净退出。

        ``asyncio.wait`` 不接受空集合；若 ``stop()`` 用空 ``_tasks`` 调它会在
        shutdown 路径抛 ValueError，掩盖原始启动错误。
        """
        queue = TaskQueue()
        worker = _worker(queue=queue)

        async def _boom_reconcile() -> None:
            raise RuntimeError("reconcile 失败")

        worker._reconcile_stale_tasks = _boom_reconcile  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="reconcile 失败"):
            await worker.start()

        # start 失败后 _started 为 True 但 _tasks 为空；stop 不应抛 ValueError。
        await worker.stop()
        assert worker.is_started is False
        assert worker._tasks == []


class TestDoneCallback:
    def test_unhandled_exception_records_crash(self) -> None:
        worker = _worker()
        worker._loop_total = 1
        worker._loop_alive = 1
        done = Mock()
        done.cancelled.return_value = False
        done.exception.return_value = RuntimeError("loop boom")
        worker._on_loop_done(done, 0)
        snap = worker.health_snapshot()
        assert snap.alive_loops == 0
        assert snap.crashed_loops == 1
        assert snap.exited_loops == 0
        assert len(snap.recent_crashes) == 1
        crash = snap.recent_crashes[0]
        assert crash["loop_index"] == 0
        assert crash["exc_type"] == "RuntimeError"
        assert crash["message"] == "loop boom"

    def test_cancellation_is_normal_exit(self) -> None:
        """shutdown 时的 cancel 属于正常退出，不计入 crashed。"""
        worker = _worker()
        worker._loop_total = 1
        worker._loop_alive = 1
        done = Mock()
        done.cancelled.return_value = True
        worker._on_loop_done(done, 0)
        snap = worker.health_snapshot()
        assert snap.alive_loops == 0
        assert snap.crashed_loops == 0
        assert snap.exited_loops == 1

    def test_normal_return_is_exit_not_crash(self) -> None:
        worker = _worker()
        worker._loop_total = 1
        worker._loop_alive = 1
        done = Mock()
        done.cancelled.return_value = False
        done.exception.return_value = None
        worker._on_loop_done(done, 0)
        snap = worker.health_snapshot()
        assert snap.alive_loops == 0
        assert snap.exited_loops == 1
        assert snap.crashed_loops == 0


class TestLoopConsumption:
    @pytest.mark.asyncio
    async def test_last_consume_at_updated_when_consuming(self) -> None:
        """实际从队列取走任务后，最近消费时间被刷新（读者抛 TaskError 是正常跳过）。"""
        queue = TaskQueue()
        reader = Mock()
        reader.get_task = Mock(side_effect=TaskError("not found"))
        worker = _worker(queue=queue, reader=reader)
        await worker.start()
        assert worker.health_snapshot().last_consume_at is None

        await queue.enqueue("some-task")
        # 等 worker 消费并返回（读者抛 TaskError，loop 不崩溃）。
        await queue.request_stop(1)
        await worker.stop()

        snap = worker.health_snapshot()
        assert snap.last_consume_at is not None
        assert snap.crashed_loops == 0
