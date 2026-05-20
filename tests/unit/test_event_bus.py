"""EventBus 行为单测：无 running loop 时不静默丢事件。

覆盖：
- 同步路径 publish 仍然把事件落进 history，并累加 ``dropped_no_loop_count``
- 同步路径 sequence 严格自增
- 限频 warning 在首次和每 100 次触发
- async 路径行为不受影响（与原有行为兼容）
- subscribe(since_seq=...) 部分回放
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from argus_py.infra.events import EventBus


class TestPublishWithoutLoop:
    """模拟 CLI 同步路径：不在 event loop 中调 publish。"""

    def test_sync_publish_appends_history(self) -> None:
        bus = EventBus(history_limit=10)
        bus.publish("task.created", "tk-1", {"foo": "bar"})

        assert bus.dropped_no_loop_count == 1
        assert len(bus._history) == 1
        ev = bus._history[0]
        assert ev.event_type == "task.created"
        assert ev.task_id == "tk-1"
        assert ev.sequence == 1
        assert ev.data == {"foo": "bar"}

    def test_sync_publish_sequence_monotonic(self) -> None:
        bus = EventBus(history_limit=10)
        for i in range(5):
            bus.publish("task.step", f"tk-{i}")
        assert bus.dropped_no_loop_count == 5
        assert [ev.sequence for ev in bus._history] == [1, 2, 3, 4, 5]

    def test_sync_publish_warns_first_and_periodically(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """首次 warn 一次，之后每 100 次 warn 一次。"""
        bus = EventBus(history_limit=200)
        caplog.set_level(logging.WARNING, logger="argus_py.infra.events")

        # 触发 101 次，预期 warn 出现在 count=1 和 count=100
        for _ in range(101):
            bus.publish("task.tick", "tk-x")

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 2
        assert "count=1 " in warnings[0].getMessage()
        assert "count=100 " in warnings[1].getMessage()

    def test_history_limit_zero_skips_history(self) -> None:
        """history_limit=0 时不写 history，但 dropped_no_loop_count 仍记录。"""
        bus = EventBus(history_limit=0)
        bus.publish("task.created", "tk-1")
        assert bus.dropped_no_loop_count == 1
        assert len(bus._history) == 0


class TestPublishWithLoop:
    """有 event loop 时走 async 路径，dropped 计数不增加。"""

    @pytest.mark.asyncio
    async def test_async_publish_does_not_count_drops(self) -> None:
        bus = EventBus(history_limit=10)
        await bus.publish_async("task.created", "tk-1", {"x": 1})
        # 直接走 publish_async，未触发 sync fallback
        assert bus.dropped_no_loop_count == 0
        assert len(bus._history) == 1

    @pytest.mark.asyncio
    async def test_publish_in_running_loop_does_not_count_drops(self) -> None:
        """有 running loop 时 publish 应创建 task，不走 sync fallback。"""
        bus = EventBus(history_limit=10)
        bus.publish("task.created", "tk-1")
        # 让事件循环跑一轮，确保异步发布完成
        import asyncio

        await asyncio.sleep(0)
        assert bus.dropped_no_loop_count == 0
        assert len(bus._history) == 1


# ─── drop-oldest 背压策略 ──────────────────────────────────────


class TestSubscriberQueueOverflow:
    """订阅队列满时的 drop-oldest 行为与可观测。"""

    @pytest.mark.asyncio
    async def test_overflow_drops_oldest_and_counts(self) -> None:
        """队列满时新事件入队、最旧出队、counter 累加。"""
        bus = EventBus(history_limit=100, subscriber_queue_size=2)
        sub = await bus.subscribe(replay=False)

        # 连发 5 条：queue size=2，丢弃 3 次（最旧 #1 #2 #3），保留 #4 #5
        for i in range(1, 6):
            await bus.publish_async("task.tick", "tk-x", {"i": i})

        assert bus.dropped_overflow_count == 3
        # 队尾两个事件是 i=4 和 i=5
        ev_first = sub.queue.get_nowait()
        ev_second = sub.queue.get_nowait()
        assert ev_first.data == {"i": 4}
        assert ev_second.data == {"i": 5}
        assert sub.queue.empty()

    @pytest.mark.asyncio
    async def test_overflow_warns_first_and_periodically(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """drop-oldest 限频 warn：首次 + 每 100 次。"""
        bus = EventBus(history_limit=500, subscriber_queue_size=1)
        await bus.subscribe(replay=False)
        caplog.set_level(logging.WARNING, logger="argus_py.infra.events")

        # 触发：第 1 条入队不丢弃，第 2 条开始每条都丢一次最旧。
        # 发 102 条 → 丢弃 101 次（count 1..101），预期 warn 在 count=1 和 100
        for i in range(102):
            await bus.publish_async("task.tick", "tk-y", {"i": i})

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert bus.dropped_overflow_count == 101
        assert len(warnings) == 2
        assert "count=1 " in warnings[0].getMessage()
        assert "count=100 " in warnings[1].getMessage()
        # 关键诊断字段应在日志里
        assert "queue_size=1" in warnings[0].getMessage()

    @pytest.mark.asyncio
    async def test_overflow_only_one_slow_subscriber_affected(self) -> None:
        """慢订阅者满了不影响其他订阅者：每个订阅者各自一份队列。"""
        bus = EventBus(history_limit=100, subscriber_queue_size=2)
        slow = await bus.subscribe(replay=False)
        fast = await bus.subscribe(replay=False)

        for i in range(5):
            await bus.publish_async("task.tick", "tk-z", {"i": i})
            # 模拟 fast 消费及时
            if not fast.queue.empty():
                fast.queue.get_nowait()

        # slow 触发 drop，fast 因为及时消费没满
        assert bus.dropped_overflow_count >= 1
        # fast 队列最多 1 条残留
        assert fast.queue.qsize() <= 1
        # slow 队列尾部是最近两条
        assert slow.queue.qsize() == 2


class TestMetrics:
    """metrics() 聚合视图。"""

    @pytest.mark.asyncio
    async def test_metrics_aggregates_counters(self) -> None:
        bus = EventBus(history_limit=10, subscriber_queue_size=2)
        sub = await bus.subscribe(task_id="tk-1", replay=False)
        for i in range(4):
            await bus.publish_async("task.tick", "tk-1", {"i": i})

        m = bus.metrics()
        assert m["sequence"] == 4
        assert m["history_size"] == 4
        assert m["global_subscribers"] == 0
        assert m["task_subscribers"] == 1
        assert m["dropped_no_loop_count"] == 0
        # subscriber_queue_size=2，发 4 条 → 丢 2 次
        assert m["dropped_overflow_count"] == 2
        assert sub.queue.qsize() == 2

    def test_metrics_keys_stable(self) -> None:
        """metrics() 字段稳定，避免上层接口被悄悄改坏。"""
        bus = EventBus(history_limit=0)
        assert set(bus.metrics().keys()) == {
            "sequence",
            "history_size",
            "global_subscribers",
            "task_subscribers",
            "max_subscribers",
            "dropped_no_loop_count",
            "dropped_overflow_count",
            "rejected_subscriber_count",
        }


class TestMaxSubscribers:
    """订阅并发上限护栏。"""

    @pytest.mark.asyncio
    async def test_default_unlimited(self) -> None:
        """max_subscribers=0 → 不限，向后兼容。"""
        bus = EventBus(history_limit=10)
        assert bus.max_subscribers == 0
        for _ in range(50):
            await bus.subscribe(task_id=None)
        assert bus.rejected_subscriber_count == 0

    @pytest.mark.asyncio
    async def test_limit_blocks_excess_subscribers(self) -> None:
        """超过 max_subscribers → 抛 EventBusSubscriberLimitError。"""
        from argus_py.infra.events import EventBusSubscriberLimitError

        bus = EventBus(history_limit=10, max_subscribers=2)
        await bus.subscribe(task_id="tk-1")
        await bus.subscribe(task_id="tk-2")

        with pytest.raises(EventBusSubscriberLimitError):
            await bus.subscribe(task_id="tk-3")
        assert bus.rejected_subscriber_count == 1

    @pytest.mark.asyncio
    async def test_global_and_task_share_quota(self) -> None:
        """全局订阅与任务订阅共用同一份配额。"""
        from argus_py.infra.events import EventBusSubscriberLimitError

        bus = EventBus(history_limit=10, max_subscribers=2)
        await bus.subscribe(task_id=None)
        await bus.subscribe(task_id="tk-1")

        with pytest.raises(EventBusSubscriberLimitError):
            await bus.subscribe(task_id="tk-2")

    @pytest.mark.asyncio
    async def test_unsubscribe_frees_quota(self) -> None:
        """unsubscribe 后配额释放，可以接受新订阅。"""
        bus = EventBus(history_limit=10, max_subscribers=1)
        sub = await bus.subscribe(task_id="tk-1")
        await sub.close()
        # 不应再抛异常
        sub2 = await bus.subscribe(task_id="tk-2")
        assert sub2 is not None

    @pytest.mark.asyncio
    async def test_rejected_count_in_metrics(self) -> None:
        from argus_py.infra.events import EventBusSubscriberLimitError

        bus = EventBus(history_limit=10, max_subscribers=1)
        await bus.subscribe(task_id="tk-1")
        for _ in range(3):
            with pytest.raises(EventBusSubscriberLimitError):
                await bus.subscribe(task_id="tk-2")
        m = bus.metrics()
        assert m["max_subscribers"] == 1
        assert m["rejected_subscriber_count"] == 3


class TestSubscribeSinceSeq:
    """subscribe(since_seq=...) 重连部分回放。"""

    @pytest.mark.asyncio
    async def test_since_seq_filters_history(self) -> None:
        bus = EventBus(history_limit=20)
        for i in range(1, 6):
            await bus.publish_async("task.step", "tk-1", {"i": i})

        sub = await bus.subscribe(task_id="tk-1", since_seq=3)
        events = _drain(sub.queue)
        assert [e.sequence for e in events] == [4, 5]

    @pytest.mark.asyncio
    async def test_since_seq_none_replays_all(self) -> None:
        """since_seq=None 回放全部历史（默认行为，保证向前兼容）。"""
        bus = EventBus(history_limit=20)
        for i in range(1, 4):
            await bus.publish_async("task.step", "tk-1", {"i": i})

        sub = await bus.subscribe(task_id="tk-1", since_seq=None)
        events = _drain(sub.queue)
        assert [e.sequence for e in events] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_since_seq_greater_than_all_returns_empty(self) -> None:
        """since_seq 大于历史最大 sequence → 没有回放事件。"""
        bus = EventBus(history_limit=20)
        for i in range(1, 4):
            await bus.publish_async("task.step", "tk-1", {"i": i})

        sub = await bus.subscribe(task_id="tk-1", since_seq=999)
        assert sub.queue.empty()

    @pytest.mark.asyncio
    async def test_since_seq_with_global_subscription_respects_task_filter(self) -> None:
        """全局订阅 + since_seq 也按 task_id 过滤后再按 sequence 过滤。"""
        bus = EventBus(history_limit=20)
        await bus.publish_async("task.step", "tk-1", {"i": 1})
        await bus.publish_async("task.step", "tk-1", {"i": 2})
        await bus.publish_async("task.step", "tk-2", {"i": 3})  # 不同任务，seq=3

        sub = await bus.subscribe(task_id="tk-1", since_seq=1)
        events = _drain(sub.queue)
        assert [e.sequence for e in events] == [2]  # tk-1 的 seq=2


def _drain(queue: asyncio.Queue) -> list:
    """排空 Queue 中所有事件，供测试断言。"""
    events: list = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events
