"""进程内事件总线。"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from argus_py.utils.jsonx import to_jsonable

logger = logging.getLogger(__name__)

# P1-7：无 running loop 时降级 publish 的告警频控阈值。
# 第一次出现立即 warn 一次；之后每 100 次 warn 一次。避免日志风暴又不淹没问题。
_NO_LOOP_WARN_FIRST = 1
_NO_LOOP_WARN_EVERY = 100

# P1-16：订阅队列满时 drop-oldest 的告警频控阈值（与 no-loop 一致）。
_OVERFLOW_WARN_FIRST = 1
_OVERFLOW_WARN_EVERY = 100


@dataclass(frozen=True)
class TaskEvent:
    """任务事件。"""

    sequence: int
    event_type: str
    task_id: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """转换为 WebSocket 可发送的字典。"""
        return {
            "sequence": self.sequence,
            "type": self.event_type,
            "taskId": self.task_id,
            "data": self.data,
            "createdAt": self.created_at.isoformat(),
        }


class EventSubscription:
    """事件订阅。"""

    def __init__(
        self, bus: "EventBus", queue: asyncio.Queue[TaskEvent], task_id: str | None
    ) -> None:
        self.bus = bus
        self.queue = queue
        self.task_id = task_id

    async def close(self) -> None:
        """关闭订阅。"""
        await self.bus.unsubscribe(self)


class EventBus:
    """内存事件总线，支持任务级和全局订阅。

    **背压策略（重要）**：每个订阅者持有独立的 ``asyncio.Queue``，容量由
    ``subscriber_queue_size``（默认 100）控制。当慢消费者（如 WebSocket 断
    连但未及时 ``unsubscribe``，或前端 UI 卡顿来不及消费）让队列填满时，
    ``_offer()`` 采用 **drop-oldest** 策略：丢弃队首未消费的最旧事件，把新事件
    放进队尾。这是经过权衡的——可选方案各自的问题：

    - drop-newest：新事件丢失，慢消费者一直停留在过期状态；
    - block：``put`` 阻塞会拖垮整个 publisher，连带影响所有订阅者；
    - 无界队列：内存无上限，慢消费者会让进程 OOM。

    drop-oldest 的代价是：**订阅端会看到 sequence 跳号**。订阅端必须容忍这种
    跳号；强一致场景应在重连时通过 ``subscribe(replay=True)`` 从 history
    回放补齐——history 容量由 ``history_limit``（默认 200）独立控制，比单个
    订阅队列大。

    丢弃次数累加到 ``dropped_overflow_count`` 暴露给 ``metrics()``；连续高位
    报警意味着消费端不稳定或队列容量需要调大，可通过 ``server.yaml`` 的
    ``events.subscriber_queue_size`` / ``events.history_limit`` 调整。
    """

    def __init__(self, history_limit: int = 200, subscriber_queue_size: int = 100) -> None:
        self.history_limit = max(0, history_limit)
        self.subscriber_queue_size = max(1, subscriber_queue_size)
        self._sequence = 0
        self._global_subscribers: set[asyncio.Queue[TaskEvent]] = set()
        self._task_subscribers: dict[str, set[asyncio.Queue[TaskEvent]]] = defaultdict(set)
        self._history: deque[TaskEvent] = deque(maxlen=self.history_limit or None)
        self._lock = asyncio.Lock()
        # P1-7：CLI / 同步路径在没有 event loop 时也能写入 history。
        # 此 lock 与 ``self._lock`` 是独立的：同步路径与 async 路径不会同时运行
        # （无 running loop 才走 sync 分支），但同步路径自己可能多线程，因此用
        # threading.Lock 保护 ``_sequence`` 与 ``_history``。
        self._sync_lock = threading.Lock()
        # 累计：无 loop 时降级到 sync 写 history 的事件数（不通知订阅者）。
        # 暴露给监控用，方便发现"有事件被产生但没人收到"的隐患。
        self.dropped_no_loop_count = 0
        # P1-16：订阅队列满时 drop-oldest 丢弃的最旧事件累计数。
        # 与 dropped_no_loop_count 分开统计，因为根因不同：前者是慢消费者，
        # 后者是发布点找不到 loop。
        self.dropped_overflow_count = 0

    def publish(self, event_type: str, task_id: str, data: dict[str, Any] | None = None) -> None:
        """发布事件。

        - 有运行中的事件循环：创建 async task 派发给所有订阅者，同时写 history
        - 无运行中的事件循环（CLI / 同步路径）：降级为只写 history（订阅者此时
          理论上不存在），同时累加 ``dropped_no_loop_count`` 并周期性 warn

        旧实现 (P0)：无 loop 时静默 return，CLI 路径下的所有事件都被吞掉，导致
        审计闭环缺数据。现在至少 history 有记录，且可观测。
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._publish_sync(event_type, task_id, data or {})
            return
        task = loop.create_task(self.publish_async(event_type, task_id, data or {}))
        task.add_done_callback(_log_publish_error)

    def _publish_sync(
        self,
        event_type: str,
        task_id: str,
        data: dict[str, Any],
    ) -> TaskEvent:
        """同步路径补救：在 history 中记录事件，不通知 async 订阅者。

        CLI 模式下没有 event loop 也就不会有 WebSocket / 异步消费者；只需要把
        事件落进 history 即可保证审计 / 后续 replay 不丢数据。
        """
        with self._sync_lock:
            self._sequence += 1
            event = TaskEvent(
                sequence=self._sequence,
                event_type=event_type,
                task_id=task_id,
                data=to_jsonable(data),
            )
            if self.history_limit:
                self._history.append(event)
            self.dropped_no_loop_count += 1
            count = self.dropped_no_loop_count
        # 限频日志（首次 + 每 100 次）：既能提示问题，又不会刷屏
        if count == _NO_LOOP_WARN_FIRST or count % _NO_LOOP_WARN_EVERY == 0:
            logger.warning(
                "事件总线无 running loop，事件已记录到 history 但未通知订阅者："
                "count=%d type=%s task=%s",
                count,
                event_type,
                task_id,
            )
        return event

    async def publish_async(
        self,
        event_type: str,
        task_id: str,
        data: dict[str, Any] | None = None,
    ) -> TaskEvent:
        """异步发布事件。"""
        async with self._lock:
            self._sequence += 1
            event = TaskEvent(
                sequence=self._sequence,
                event_type=event_type,
                task_id=task_id,
                data=to_jsonable(data or {}),
            )
            if self.history_limit:
                self._history.append(event)
            targets = set(self._global_subscribers)
            targets.update(self._task_subscribers.get(task_id, set()))

        for queue in targets:
            self._offer(queue, event)
        return event

    async def subscribe(self, task_id: str | None = None, replay: bool = True) -> EventSubscription:
        """创建事件订阅。"""
        queue: asyncio.Queue[TaskEvent] = asyncio.Queue(maxsize=self.subscriber_queue_size)
        async with self._lock:
            if task_id is None:
                self._global_subscribers.add(queue)
            else:
                self._task_subscribers[task_id].add(queue)
            if replay:
                for event in self._history:
                    if task_id is None or event.task_id == task_id:
                        self._offer(queue, event)
        return EventSubscription(self, queue, task_id)

    async def unsubscribe(self, subscription: EventSubscription) -> None:
        """取消事件订阅。"""
        async with self._lock:
            if subscription.task_id is None:
                self._global_subscribers.discard(subscription.queue)
            else:
                subscribers = self._task_subscribers.get(subscription.task_id)
                if subscribers is not None:
                    subscribers.discard(subscription.queue)
                    if not subscribers:
                        self._task_subscribers.pop(subscription.task_id, None)

    def _offer(self, queue: asyncio.Queue[TaskEvent], event: TaskEvent) -> None:
        """向订阅队列投递事件；满队列时执行 drop-oldest 并记录可观测信息。

        参见 ``EventBus`` 类文档的"背压策略"小节。简言之：

        1. 队列未满：直接 ``put_nowait``；
        2. 队列已满：``get_nowait`` 丢掉最旧事件腾位再 ``put_nowait``，并把
           ``dropped_overflow_count`` 加一，按 (首次 + 每 100 次) 频控写
           WARN 日志，便于运维定位慢消费者；
        3. 极端 race（同 tick 内被填满）：再次 ``QueueFull`` 时静默放弃，避免
           异常上抛中断 publish 链。

        本方法假设在 asyncio 单线程上下文调用，因此对 ``dropped_overflow_count``
        的非原子自增是安全的。
        """
        if not queue.full():
            queue.put_nowait(event)
            return
        try:
            queue.get_nowait()
            queue.task_done()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # 极端情况：get 与 put 之间又被填满。直接放弃新事件，
            # 这种情况算作两次 drop（最旧 + 当前新事件），但只计一次以避免
            # 误报；订阅端应通过 history replay 补齐。
            pass
        self.dropped_overflow_count += 1
        count = self.dropped_overflow_count
        if count == _OVERFLOW_WARN_FIRST or count % _OVERFLOW_WARN_EVERY == 0:
            logger.warning(
                "事件总线订阅队列已满，丢弃最旧事件：count=%d type=%s task=%s queue_size=%d",
                count,
                event.event_type,
                event.task_id,
                self.subscriber_queue_size,
            )

    def metrics(self) -> dict[str, int]:
        """返回 EventBus 关键运行指标，供 healthz / 监控接口聚合。

        P1-16 新增：把分散的计数器集中暴露，避免上层直接探属性。字段含义：

        - ``sequence``：自启动以来发布的事件总数；
        - ``history_size``：history 缓冲中当前事件数；
        - ``global_subscribers`` / ``task_subscribers``：当前活跃订阅者数；
        - ``dropped_no_loop_count``：见 ``publish`` 文档；
        - ``dropped_overflow_count``：见 ``_offer`` 文档。
        """
        return {
            "sequence": self._sequence,
            "history_size": len(self._history),
            "global_subscribers": len(self._global_subscribers),
            "task_subscribers": sum(len(s) for s in self._task_subscribers.values()),
            "dropped_no_loop_count": self.dropped_no_loop_count,
            "dropped_overflow_count": self.dropped_overflow_count,
        }


def _log_publish_error(task: asyncio.Task[object]) -> None:
    """记录事件发布异步任务中的未处理异常。"""
    exc = task.exception()
    if exc:
        logger.error("事件发布失败: %s", exc)
