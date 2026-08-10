"""O-03 有界队列准入控制测试。

覆盖 ``TaskQueue.try_enqueue`` 的原子性（满载不残留 ``_queued_ids``）、幂等
去重、容量/压力指标，以及 start/restart 在队列满载时的应用层语义（错误码 /
HTTP 503 / Retry-After / restart 子任务回滚）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from argus_py.infra.queue import TaskQueue
from argus_py.task.application import QUEUE_FULL_RETRY_AFTER_SECONDS, TaskAppError

from tests.helpers.factories import make_app_stack

# ── TaskQueue.try_enqueue 原子性与幂等 ────────────────────────────────────────


class TestTryEnqueue:
    @pytest.mark.asyncio
    async def test_concurrent_admission_never_exceeds_capacity(self) -> None:
        """并发提交超过容量时只接收 capacity 个，其余立即拒绝。"""
        queue = TaskQueue(max_size=3)
        results = await asyncio.gather(*(queue.try_enqueue(f"t{i}") for i in range(20)))

        accepted = [result for result in results if not result.rejected]
        rejected = [result for result in results if result.rejected]
        assert len(accepted) == 3
        assert len(rejected) == 17
        assert await queue.counts() == {"queued": 3, "active": 0}
        metrics = await queue.metrics()
        assert metrics["utilization"] == 1.0
        assert metrics["rejected_total"] == 17

    @pytest.mark.asyncio
    async def test_rejects_when_full_without_residue(self) -> None:
        """满载时拒绝且不在 _queued_ids 残留，队列状态与指标一致。"""
        queue = TaskQueue(max_size=1)
        assert (await queue.try_enqueue("t1")).rejected is False
        assert (await queue.try_enqueue("t1")).already_known is True  # 去重在容量之前

        result = await queue.try_enqueue("t2")
        assert result.rejected is True
        assert result.scheduler_status == "full"
        assert await queue.scheduler_status("t2") is None
        assert await queue.counts() == {"queued": 1, "active": 0}
        metrics = await queue.metrics()
        assert metrics["rejected_total"] == 1

    @pytest.mark.asyncio
    async def test_dedup_precedes_capacity(self) -> None:
        """已入队/执行中的任务即使队列满载也返回幂等命中，不误报满载。"""
        queue = TaskQueue(max_size=1)
        await queue.try_enqueue("t1")

        again = await queue.try_enqueue("t1")
        assert again.already_known is True
        assert again.rejected is False

        # t1 被取出进入 active 后再次提交仍幂等
        assert await queue.get() == "t1"
        active = await queue.try_enqueue("t1")
        assert active.already_known is True
        assert active.scheduler_status == "running"
        assert active.rejected is False
        await queue.complete("t1")

    @pytest.mark.asyncio
    async def test_metrics_reflect_capacity_and_rejected(self) -> None:
        """metrics 返回 capacity/utilization/oldest age/rejected。"""
        queue = TaskQueue(max_size=2)
        await queue.try_enqueue("t1")
        await queue.try_enqueue("t2")
        assert (await queue.try_enqueue("t3")).rejected is True

        m = await queue.metrics()
        assert m["capacity"] == 2
        assert m["queued"] == 2
        assert m["active"] == 0
        assert m["utilization"] == 1.0
        assert m["rejected_total"] == 1
        assert m["oldest_queued_age_seconds"] >= 0.0

        # 全部出队后 oldest age 回到 -1（无排队）
        assert await queue.get() == "t1"
        await queue.complete("t1")
        assert await queue.get() == "t2"
        await queue.complete("t2")
        assert (await queue.metrics())["oldest_queued_age_seconds"] == -1.0

    @pytest.mark.asyncio
    async def test_unbounded_queue_never_rejects(self) -> None:
        """max_size=0（无界）时不产生 rejected，utilization 恒 0。"""
        queue = TaskQueue(max_size=0)
        for i in range(50):
            assert (await queue.try_enqueue(f"t{i}")).rejected is False
        m = await queue.metrics()
        assert m["capacity"] == 0
        assert m["queued"] == 50
        assert m["utilization"] == 0.0

    @pytest.mark.asyncio
    async def test_cancelled_full_slot_is_drained_before_next_admission(self) -> None:
        """取消项采用 tombstone：Worker 跳过后容量可再次准入，状态不残留。"""
        queue = TaskQueue(max_size=1)
        await queue.try_enqueue("cancelled")
        assert await queue.cancel("cancelled") is True
        assert await queue.counts() == {"queued": 0, "active": 0}

        # 物理槽位仍由 tombstone 占用，因此消费前的新请求快速失败而不是阻塞。
        assert (await queue.try_enqueue("too-early")).rejected is True
        pending_get = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        assert (await queue.try_enqueue("next")).rejected is False
        assert await asyncio.wait_for(pending_get, 1) == "next"
        await queue.complete("next")

    @pytest.mark.asyncio
    async def test_shutdown_signal_waits_for_full_queue_then_completes(self) -> None:
        """满载停机不会丢哨兵：排空一个槽位后 shutdown 信号可完成投递。"""
        queue = TaskQueue(max_size=1)
        await queue.try_enqueue("queued")
        stop = asyncio.create_task(queue.request_stop(1))
        await asyncio.sleep(0)
        assert stop.done() is False

        assert await queue.get() == "queued"
        await queue.complete("queued")
        await asyncio.wait_for(stop, 1)
        assert await queue.get() is None
        await queue.complete(None)


# ── 应用层：start/restart 队列满载语义 ───────────────────────────────────────


class TestApplicationQueueFull:
    @pytest.mark.asyncio
    async def test_start_task_queue_full_503_and_task_stays_pending(self, tmp_path: Path) -> None:
        """start 在队列满载时抛 TASK_QUEUE_FULL（503 + Retry-After），任务保持 pending。"""
        stack = make_app_stack(tmp_path, queue_max_size=1)
        await stack.queue.try_enqueue("occupy-queue")
        pending = stack.lifecycle.create_task(goal="无法入队", start_url="https://example.com")

        with pytest.raises(TaskAppError) as exc_info:
            await stack.app.start_task(pending.task_id)

        exc = exc_info.value
        assert exc.code == "TASK_QUEUE_FULL"
        assert exc.http_status == 503
        assert exc.details["retry_after_seconds"] == QUEUE_FULL_RETRY_AFTER_SECONDS
        assert exc.details["capacity"] == 1
        assert exc.details["queued"] == 1
        # 任务未入队，仍可稍后重试
        assert await stack.queue.scheduler_status(pending.task_id) is None
        assert stack.reader.get_task(pending.task_id).status.value == "pending"

    @pytest.mark.asyncio
    async def test_start_queue_full_but_task_already_queued_is_idempotent(
        self, tmp_path: Path
    ) -> None:
        """队列满载但任务已在队列：幂等命中（TASK_ALREADY_SCHEDULED）而非误报满载。

        客户端重试语义：任务已入队时，即使队列满也返回"已调度"（409），
        不会把幂等重试误判成过载。
        """
        stack = make_app_stack(tmp_path, queue_max_size=1)
        pending = stack.lifecycle.create_task(goal="已入队", start_url="https://example.com")
        await stack.queue.try_enqueue(pending.task_id)  # 同时占满队列

        with pytest.raises(TaskAppError) as exc_info:
            await stack.app.start_task(pending.task_id)

        assert exc_info.value.code == "TASK_ALREADY_SCHEDULED"
        assert exc_info.value.http_status == 409
        assert (await stack.queue.metrics())["rejected_total"] == 0

    @pytest.mark.asyncio
    async def test_restart_queue_full_rolls_back_child(self, tmp_path: Path) -> None:
        """restart 在队列满载时回滚已创建的 retry 子任务，父任务恢复重试资格。"""
        stack = make_app_stack(tmp_path, queue_max_size=1)
        parent = stack.lifecycle.create_task(goal="重试队列满", start_url="https://example.com")
        # PENDING → RUNNING → FAILED，使任务进入可重试终态
        stack.lifecycle.start_task(parent)
        stack.lifecycle.fail_task(parent, "测试失败")

        await stack.queue.try_enqueue("occupy-queue")
        with pytest.raises(TaskAppError) as exc_info:
            await stack.app.restart_task(parent.task_id)
        assert exc_info.value.code == "TASK_QUEUE_FULL"
        assert exc_info.value.http_status == 503
        # 回滚：没有残留 retry 子任务，父任务仍可重试
        assert stack.lifecycle.has_retry_child(parent.task_id) is False

        # 释放队列空位后重试成功：子任务创建并入队
        assert await stack.queue.get() == "occupy-queue"
        await stack.queue.complete("occupy-queue")
        new_task, sched = await stack.app.restart_task(parent.task_id)
        assert sched == "queued"
        assert stack.lifecycle.has_retry_child(parent.task_id) is True
        assert await stack.queue.scheduler_status(new_task.task_id) == "queued"
