"""进程内事件总线。"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from argus_py.utils.jsonx import to_jsonable


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
        return to_jsonable(
            {
                "sequence": self.sequence,
                "type": self.event_type,
                "taskId": self.task_id,
                "data": self.data,
                "createdAt": self.created_at,
            }
        )


class EventSubscription:
    """事件订阅。"""

    def __init__(self, bus: "EventBus", queue: asyncio.Queue[TaskEvent], task_id: str | None) -> None:
        self.bus = bus
        self.queue = queue
        self.task_id = task_id

    async def close(self) -> None:
        """关闭订阅。"""
        await self.bus.unsubscribe(self)


class EventBus:
    """内存事件总线，支持任务级和全局订阅。"""

    def __init__(self, history_limit: int = 200, subscriber_queue_size: int = 100) -> None:
        self.history_limit = max(0, history_limit)
        self.subscriber_queue_size = max(1, subscriber_queue_size)
        self._sequence = 0
        self._global_subscribers: set[asyncio.Queue[TaskEvent]] = set()
        self._task_subscribers: dict[str, set[asyncio.Queue[TaskEvent]]] = defaultdict(set)
        self._history: deque[TaskEvent] = deque(maxlen=self.history_limit or None)
        self._lock = asyncio.Lock()

    def publish(self, event_type: str, task_id: str, data: dict[str, Any] | None = None) -> None:
        """发布事件；没有运行中的事件循环时静默跳过。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.publish_async(event_type, task_id, data or {}))

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
        """向订阅队列投递事件，满队列时丢弃最旧事件。"""
        if queue.full():
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)
