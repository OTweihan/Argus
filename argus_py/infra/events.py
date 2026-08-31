"""进程内事件总线。"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from argus_py.core.ids import generate_id
from argus_py.utils.jsonx import to_jsonable

logger = logging.getLogger(__name__)

# 无 running loop 时降级 publish 的告警频控阈值：第一次出现立即 warn 一次；
# 之后每 100 次 warn 一次。避免日志风暴又不淹没问题。
_NO_LOOP_WARN_FIRST = 1
_NO_LOOP_WARN_EVERY = 100

# 订阅队列满时 drop-oldest 的告警频控阈值（与 no-loop 一致）。
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
            "eventType": self.event_type,
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


class EventBusSubscriberLimitError(RuntimeError):
    """当前订阅者数已达 ``max_subscribers`` 上限，新订阅被拒绝。

    用于让 WebSocket 路由识别"系统已满载"并返回 1013（service overload），
    与正常业务错误（1008 policy violation）区分开。
    """


@dataclass(frozen=True)
class ReplayWindow:
    """一次进程生命周期内的可回放事件窗口快照。

    Attributes:
        stream_epoch: 进程级事件流纪元（EventBus 构造时生成，重启即变化）。
            WebSocket 客户端用它识别"服务重启后 sequence 空间不连续"。
        oldest_sequence: history 中可回放的最早 sequence；history 为空时为
            ``current_sequence + 1``（表示无任何可回放事件）。
        current_sequence: 当前最新已发布 sequence。
    """

    stream_epoch: str
    oldest_sequence: int
    current_sequence: int


@dataclass(frozen=True)
class EventSubscriptionResult:
    """``subscribe_with_replay`` 的返回：订阅 + 有界回放批次 + 回放窗口。

    回放事件以普通列表返回（不经过 ``subscriber_queue_size`` 的订阅队列），
    由调用方（WebSocket 路由）分批直发，避免 history 容量大于订阅队列时
    回放被 drop-oldest 静默丢弃。
    """

    subscription: EventSubscription
    replay_events: list[TaskEvent]
    replay_complete: bool
    window: ReplayWindow


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
    订阅队列大。**注意**：``subscribe`` 的回放仍经订阅队列，history 大于队列
    容量时会被 drop-oldest；WebSocket 等需要无丢失回放的调用方使用
    ``subscribe_with_replay`` 获取有界回放批次直发。

    sequence 在进程内单调递增、重启归零。``stream_epoch`` 在构造时生成并随
    进程重启变化，客户端据此识别"sequence 空间不连续"，避免用重启前的高
    sequence 跳过新进程已积累的历史（见 ``system.ready`` / ``system.replay_gap``
    协议）。

    丢弃次数累加到 ``dropped_overflow_count`` 暴露给 ``metrics()``；连续高位
    报警意味着消费端不稳定或队列容量需要调大，可通过 ``server.yaml`` 的
    ``events.subscriber_queue_size`` / ``events.history_limit`` 调整。
    """

    def __init__(
        self,
        history_limit: int = 200,
        subscriber_queue_size: int = 100,
        max_subscribers: int = 0,
    ) -> None:
        self.history_limit = max(0, history_limit)
        self.subscriber_queue_size = max(1, subscriber_queue_size)
        # max_subscribers=0 表示不限制（向后兼容）；>0 时作为全局并发订阅上限，
        # 防止恶意/异常前端反复重连耗尽 asyncio.Queue 内存（每订阅独占一队列）。
        self.max_subscribers = max(0, max_subscribers)
        # 进程级事件流纪元：服务重启后变化。sequence 从 0 重新计数，客户端若用
        # 重启前的高 sequence 请求回放会跳过新进程已积累的历史；WebSocket 路由
        # 在 ``system.ready`` 中下发本纪元，客户端重连时带上旧纪元，服务端比对
        # 不一致则判定 epoch 变化，通知客户端丢弃旧 cursor 并从权威接口重建。
        self.stream_epoch = generate_id("ev")
        self._sequence = 0
        self._global_subscribers: set[asyncio.Queue[TaskEvent]] = set()
        self._task_subscribers: dict[str, set[asyncio.Queue[TaskEvent]]] = defaultdict(set)
        self._history: deque[TaskEvent] = deque(maxlen=self.history_limit or None)
        self._lock = asyncio.Lock()
        # Web/API 运行时所属事件循环。生命周期方法可能在线程池执行，事件必须
        # 通过该 loop 回投，不能误走 CLI 的 sync-history 降级路径。
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        # 累计：因 max_subscribers 上限被拒的订阅次数。暴露给监控，方便发现
        # "前端反复重连且容量需要调大" 或 "存在异常调用方" 的隐患。
        self.rejected_subscriber_count = 0
        # CLI / 同步路径在没有 event loop 时也能写入 history。
        # 此 lock 与 ``self._lock`` 是独立的：同步路径与 async 路径不会同时运行
        # （无 running loop 才走 sync 分支），但同步路径自己可能多线程，因此用
        # threading.Lock 保护 ``_sequence`` 与 ``_history``。
        self._sync_lock = threading.Lock()
        # 累计：无 loop 时降级到 sync 写 history 的事件数（不通知订阅者）。
        # 暴露给监控用，方便发现"有事件被产生但没人收到"的隐患。
        self.dropped_no_loop_count = 0
        # 订阅队列满时 drop-oldest 丢弃的最旧事件累计数。
        # 与 dropped_no_loop_count 分开统计，因为根因不同：前者是慢消费者，
        # 后者是发布点找不到 loop。
        self.dropped_overflow_count = 0

        # --- tick 级事件合并 ---
        # 同 tick 内 publish 多次时合并成单次 async dispatch，减少 create_task 开销。
        self._tick_buffer: list[tuple[str, str, dict[str, Any]]] = []
        self._flush_task_created = False
        self._tick_lock = threading.Lock()
        self.coalesced_batch_count = 0
        self.coalesced_event_count = 0

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """绑定 Web/API 所属事件循环，供工作线程安全回投实时事件。"""
        self._owner_loop = loop

    def unbind_loop(self) -> None:
        """解除事件循环绑定；关闭阶段之后的同步发布退回 history。"""
        self._owner_loop = None

    def publish(self, event_type: str, task_id: str, data: dict[str, Any] | None = None) -> None:
        """发布事件。

        - 有运行中的事件循环：缓冲到 tick buffer，由 ``_dispatch_batch`` 合并派发
        - 当前线程无事件循环、但 Web/API owner loop 正在运行：线程安全回投 owner loop
        - 未绑定 owner loop（CLI / 纯同步路径）：降级为只写 history，同时累加
          ``dropped_no_loop_count`` 并周期性 warn

        早期实现里无 loop 时静默 return，CLI 路径下的所有事件都被吞掉，导致
        审计闭环缺数据。现在至少 history 有记录，且可观测。
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            owner_loop = self._owner_loop
            if owner_loop is not None and owner_loop.is_running():
                try:
                    owner_loop.call_soon_threadsafe(self.publish, event_type, task_id, data)
                except RuntimeError:
                    # loop 在 is_running() 与投递之间关闭：按同步路径保留 history。
                    pass
                else:
                    return
            self._publish_sync(event_type, task_id, data or {})
            return

        with self._tick_lock:
            self._tick_buffer.append((event_type, task_id, data or {}))
        if not self._flush_task_created:
            self._flush_task_created = True
            task = loop.create_task(self._dispatch_batch())
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

    async def _dispatch_batch(self) -> None:
        """合并处理 tick buffer 中的所有事件，单次 async dispatch。"""
        with self._tick_lock:
            buffer = self._tick_buffer[:]
            self._tick_buffer.clear()

        if not buffer:
            self._flush_task_created = False
            return

        self.coalesced_batch_count += 1
        self.coalesced_event_count += len(buffer)

        events: list[TaskEvent] = []
        async with self._lock:
            for event_type, task_id, data in buffer:
                self._sequence += 1
                event = TaskEvent(
                    sequence=self._sequence,
                    event_type=event_type,
                    task_id=task_id,
                    data=to_jsonable(data),
                )
                events.append(event)
                if self.history_limit:
                    self._history.append(event)

            for queue in self._global_subscribers:
                for evt in events:
                    self._offer(queue, evt)

            if self._task_subscribers:
                tid_events: dict[str, list[TaskEvent]] = {}
                for evt in events:
                    tid_events.setdefault(evt.task_id, []).append(evt)
                for tid, evts in tid_events.items():
                    for queue in self._task_subscribers.get(tid, set()):
                        for evt in evts:
                            self._offer(queue, evt)

        self._flush_task_created = False

        if self._tick_buffer and not self._flush_task_created:
            self._flush_task_created = True
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            task = loop.create_task(self._dispatch_batch())
            task.add_done_callback(_log_publish_error)

    async def subscribe(
        self,
        task_id: str | None = None,
        replay: bool = True,
        since_seq: int | None = None,
    ) -> EventSubscription:
        """创建事件订阅。

        Args:
            task_id: 订阅特定任务的事件，None 表示全局。
            replay: 是否回放 history 中已有事件。
            since_seq: 只回放 sequence > since_seq 的事件，用于重连补齐。
                      为 None 时回放全部 history。

        Raises:
            EventBusSubscriberLimitError: 当 ``max_subscribers>0`` 且当前订阅总数
                已达上限。WebSocket 路由应捕获该异常并回 1013（service overload）
                而不是 1008，让前端区分"限流可重试"和"业务规则拒绝"。

        注意：回放经 ``_offer`` 进入订阅队列，history 容量大于
        ``subscriber_queue_size`` 时回放会被 drop-oldest。需要无丢失回放的
        调用方应使用 ``subscribe_with_replay``。
        """
        async with self._lock:
            queue = self._register_subscriber_locked(task_id)
            if replay:
                for event in self._history:
                    if task_id is None or event.task_id == task_id:
                        if since_seq is None or event.sequence > since_seq:
                            self._offer(queue, event)
        return EventSubscription(self, queue, task_id)

    async def subscribe_with_replay(
        self,
        task_id: str | None = None,
        since_seq: int | None = None,
    ) -> EventSubscriptionResult:
        """订阅并返回有界回放批次，供 WebSocket 直发（O-05）。

        与 ``subscribe`` 的差异：回放事件收集为普通列表返回（最多
        ``history_limit`` 条），而不是先塞进 ``subscriber_queue_size`` 的队列
        ——避免 history 容量大于订阅队列时回放被 drop-oldest 静默丢弃。注册订阅
        与收集回放同在 ``self._lock`` 内完成，保证"回放批次 + 之后的实时事件"
        无缝衔接、无重复无遗漏。

        返回的 ``ReplayWindow`` 携带 ``stream_epoch`` / ``oldest_sequence`` /
        ``current_sequence``，供路由在 ``system.ready`` 下发、客户端检测服务
        重启后的 epoch 变化。
        """
        replay_events: list[TaskEvent] = []
        async with self._lock:
            queue = self._register_subscriber_locked(task_id)
            for event in self._history:
                if task_id is None or event.task_id == task_id:
                    if since_seq is None or event.sequence > since_seq:
                        replay_events.append(event)
            window = self._replay_window_locked()
        return EventSubscriptionResult(
            subscription=EventSubscription(self, queue, task_id),
            replay_events=replay_events,
            # 有界列表收集无溢出，恒为 True；预留字段兼容未来分页回放实现。
            replay_complete=True,
            window=window,
        )

    def _register_subscriber_locked(self, task_id: str | None) -> asyncio.Queue[TaskEvent]:
        """在持有 ``self._lock`` 时创建并注册订阅队列。

        超过 ``max_subscribers`` 上限时抛 ``EventBusSubscriberLimitError`` 并
        累加 ``rejected_subscriber_count``。供 ``subscribe`` 与
        ``subscribe_with_replay`` 复用。
        """
        queue: asyncio.Queue[TaskEvent] = asyncio.Queue(maxsize=self.subscriber_queue_size)
        if self.max_subscribers > 0:
            current_total = len(self._global_subscribers) + sum(
                len(s) for s in self._task_subscribers.values()
            )
            if current_total >= self.max_subscribers:
                self.rejected_subscriber_count += 1
                logger.warning(
                    "事件总线订阅已达上限，拒绝新订阅：current=%d max=%d rejected_total=%d",
                    current_total,
                    self.max_subscribers,
                    self.rejected_subscriber_count,
                )
                raise EventBusSubscriberLimitError(f"事件订阅已达上限 {self.max_subscribers}")
        if task_id is None:
            self._global_subscribers.add(queue)
        else:
            self._task_subscribers[task_id].add(queue)
        return queue

    async def replay_window(self) -> ReplayWindow:
        """返回当前可回放事件窗口快照（不创建订阅）。"""
        async with self._lock:
            return self._replay_window_locked()

    def _replay_window_locked(self) -> ReplayWindow:
        """在持有 ``self._lock`` 时计算回放窗口。"""
        return ReplayWindow(
            stream_epoch=self.stream_epoch,
            oldest_sequence=self._history[0].sequence if self._history else self._sequence + 1,
            current_sequence=self._sequence,
        )

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

    def is_dispatchable(self) -> bool:
        """readiness 用轻量检查：事件总线能否向订阅者派发事件。

        无 running loop 时 ``publish`` 降级为只写 history、不通知订阅者
        （WebSocket 事件会丢失），此时不应判定为就绪。只做只读检查，不发布
        探针事件，避免高频就绪轮询污染 history。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return True

    def metrics(self) -> dict[str, int]:
        """返回 EventBus 关键运行指标，供 healthz / 监控接口聚合。

        把分散的计数器集中暴露，避免上层直接探属性。字段含义：

        - ``sequence``：自启动以来发布的事件总数；
        - ``history_size``：history 缓冲中当前事件数；
        - ``global_subscribers`` / ``task_subscribers``：当前活跃订阅者数；
        - ``dropped_no_loop_count``：见 ``publish`` 文档；
        - ``dropped_overflow_count``：见 ``_offer`` 文档；
        - ``coalesced_batch_count`` / ``coalesced_event_count``：tick 合并统计。
        """
        return {
            "sequence": self._sequence,
            "history_size": len(self._history),
            "global_subscribers": len(self._global_subscribers),
            "task_subscribers": sum(len(s) for s in self._task_subscribers.values()),
            "max_subscribers": self.max_subscribers,
            "dropped_no_loop_count": self.dropped_no_loop_count,
            "dropped_overflow_count": self.dropped_overflow_count,
            "rejected_subscriber_count": self.rejected_subscriber_count,
            "coalesced_batch_count": self.coalesced_batch_count,
            "coalesced_event_count": self.coalesced_event_count,
        }


def _log_publish_error(task: asyncio.Task[object]) -> None:
    """记录事件发布异步任务中的未处理异常。"""
    exc = task.exception()
    if exc:
        logger.error("事件发布失败: %s", exc, exc_info=True)
