"""WebSocket 实时事件路由。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

from argus_py.api.auth import (
    WS_TICKET_TTL_SECONDS,
    WebSocketTicketError,
    consume_ws_ticket,
    issue_ws_ticket,
)
from argus_py.api.dependencies import get_event_bus, get_task_read_service
from argus_py.config.server_settings import load_server_settings
from argus_py.infra.events import (
    EventBus,
    EventBusSubscriberLimitError,
    EventSubscription,
    EventSubscriptionResult,
    ReplayWindow,
    TaskEvent,
)
from argus_py.observability.context import run_in_thread
from argus_py.task.read import TaskReadService

logger = logging.getLogger(__name__)

# 服务端发心跳的间隔（秒）。前端 ws.ts 以 2.5× 此值判定断连，调整时同步更新前端。
WS_KEEPALIVE_SECONDS = 30.0

# 回放事件直发批次大小：回放经 subscribe_with_replay 收集为有界列表后分批推送，
# 避免先塞进比 history 更小的订阅队列导致 drop-oldest。
REPLAY_BATCH_SIZE = 100

# 断连轮询间隔（秒）：主循环用 wait_for 以该间隔醒来检查 disconnected 标记。
# 与 WS_KEEPALIVE_SECONDS 解耦——断连释放订阅队列要快，心跳节律要保持 30s。
_DISCONNECT_POLL_SECONDS = 1.0

# CORS allow list 模块级缓存：避免每次 WS 连接都读磁盘 parse YAML。
# 生产容器中 server.yaml 在部署后不会变更，一次性加载即可；开发环境
# 修改 yaml 后重启进程即可刷新。
_cors_origins_cache: list[str] | None = None

router = APIRouter(prefix="/ws", tags=["websocket"])


@router.post("/token")
async def issue_ws_token(request: Request) -> dict[str, Any]:
    """浏览器用 Bearer API Token 换取短时单次 WebSocket ticket。

    长期 Token 不应出现在 WebSocket URL 的 query 中（会进入反代/接入日志），
    因此浏览器先调用本端点换取一个短时、单次、HMAC 签名的 ticket，再带
    ``?token=<ticket>`` 建立 WebSocket。ticket 由 AuthTokenMiddleware 校验，
    默认 30 秒内有效、每个 ticket 只能使用一次。
    """
    try:
        ticket = issue_ws_ticket(request.app)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "token": ticket,
        "expiresIn": WS_TICKET_TTL_SECONDS,
        "singleUse": True,
    }


def _parse_since_seq(websocket: WebSocket) -> int | None:
    """从 WebSocket 查询参数中提取 ``sinceSeq``（客户端重连时传入）。"""
    raw = websocket.query_params.get("sinceSeq")
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _parse_stream_epoch(websocket: WebSocket) -> str | None:
    """从 WebSocket 查询参数中提取 ``epoch``（客户端上次连接的 streamEpoch）。

    客户端重连时带上旧纪元；服务端比对不一致即判定"服务重启后 sequence 空间
    不连续"，发送 ``system.replay_gap`` 并回放完整 history。
    """
    raw = websocket.query_params.get("epoch")
    return raw.strip() if raw else None


def _consume_ws_ticket(websocket: WebSocket) -> bool:
    """消费中间件已放行的 WebSocket ticket（单次使用扣减）。

    中间件只做非消费式放行；这里在连接被接受前真正消耗 ticket。长期 Token
    连接（CLI / 服务器到服务器）或未启用鉴权时不需要消费，直接放行。
    """
    state = websocket.scope.get("state") or {}
    if state.get("argus_ws_auth") != "ticket":
        return True
    ticket = state.get("argus_ws_ticket")
    try:
        consume_ws_ticket(websocket.app, ticket or "")
    except (WebSocketTicketError, ValueError):
        return False
    return True


def _is_origin_allowed(websocket: WebSocket) -> bool:
    """校验 WebSocket Origin 与 CORS allow list 对齐。

    私网部署同样需要这道防线：内网用户的浏览器在任意页面（内部 wiki、其他后台
    被注入脚本等）都可能发起跨域 WebSocket 连接，从而读取任务实时事件（含
    LLM 输入输出等敏感信息）。FastAPI 的 ``CORSMiddleware`` 不覆盖 WebSocket，
    必须在路由层补上。

    - 无 Origin 头：放行（CLI / 服务器到服务器调用没有 Origin）
    - allow list 含 ``*``：放行（与 CORS 行为对齐，等价于 "公开" 部署）
    - 否则要求 Origin 精确出现在 ``cors_allow_origins`` 中

    ``cors_allow_origins`` 首次加载后模块级缓存，后续连接不再读磁盘。
    """
    global _cors_origins_cache
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    if _cors_origins_cache is None:
        try:
            _cors_origins_cache = load_server_settings().cors_allow_origins
        except Exception:
            logger.warning(
                "WebSocket origin 校验时加载 server settings 失败，按拒绝处理",
                exc_info=True,
            )
            return False
    if "*" in _cors_origins_cache:
        return True
    return origin in _cors_origins_cache


@router.websocket("/tasks/{task_id}")
async def task_events(
    websocket: WebSocket,
    task_id: str,
    event_bus: EventBus = Depends(get_event_bus),
    reader: TaskReadService = Depends(get_task_read_service),
) -> None:
    """订阅单个任务的实时事件。"""
    if not _is_origin_allowed(websocket) or not _consume_ws_ticket(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    since_seq = _parse_since_seq(websocket)
    client_epoch = _parse_stream_epoch(websocket)
    # SQLite 读阻塞事件循环时 WebSocket 心跳会被拖慢，挪去线程池。
    if not await run_in_thread(reader.task_exists, task_id):
        await websocket.send_json(
            _system_event("system.error", task_id=task_id, message=f"任务不存在：{task_id}")
        )
        await websocket.close(code=1008)
        return

    try:
        result, gap_reason = await _subscribe_with_gap_detection(
            event_bus, task_id=task_id, since_seq=since_seq, client_epoch=client_epoch
        )
    except EventBusSubscriberLimitError as exc:
        await websocket.send_json(_system_event("system.error", task_id=task_id, message=str(exc)))
        # 1013 service overload：让前端区分"系统忙，可重试"与 1008 业务拒绝。
        await websocket.close(code=1013)
        return
    await _send_ready_with_replay(
        websocket,
        result=result,
        task_id=task_id,
        client_epoch=client_epoch,
        requested_since_seq=since_seq,
        gap_reason=gap_reason,
    )
    await _stream_events(websocket, result.subscription)


@router.websocket("/tasks")
async def all_task_events(
    websocket: WebSocket,
    event_bus: EventBus = Depends(get_event_bus),
) -> None:
    """订阅所有任务的实时事件。"""
    if not _is_origin_allowed(websocket) or not _consume_ws_ticket(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    since_seq = _parse_since_seq(websocket)
    client_epoch = _parse_stream_epoch(websocket)
    try:
        result, gap_reason = await _subscribe_with_gap_detection(
            event_bus, task_id=None, since_seq=since_seq, client_epoch=client_epoch
        )
    except EventBusSubscriberLimitError as exc:
        await websocket.send_json(_system_event("system.error", message=str(exc)))
        await websocket.close(code=1013)
        return
    await _send_ready_with_replay(
        websocket,
        result=result,
        task_id=None,
        client_epoch=client_epoch,
        requested_since_seq=since_seq,
        gap_reason=gap_reason,
    )
    await _stream_events(websocket, result.subscription)


async def _subscribe_with_gap_detection(
    event_bus: EventBus,
    *,
    task_id: str | None,
    since_seq: int | None,
    client_epoch: str | None,
) -> tuple[EventSubscriptionResult, str | None]:
    """订阅并检测回放缺口，返回 (订阅结果, 缺口原因或 None)。

    在订阅前基于客户端纪元决定有效 sinceSeq，只订阅一次，避免"关闭旧订阅后
    重新订阅"两步之间的窗口丢事件，也避免二次订阅撞 ``max_subscribers``：

    - ``epoch_changed``：客户端带旧纪元（服务重启后 sequence 空间不连续），
      旧 sinceSeq 无意义，丢弃后回放完整 history；
    - ``since_seq_out_of_window``：sinceSeq 早于可回放窗口，保留订阅并回放
      窗口内全部可回放事件。
    """
    gap_reason: str | None = None
    if client_epoch is not None and client_epoch != event_bus.stream_epoch:
        gap_reason = "epoch_changed"
        since_seq = None
    result = await event_bus.subscribe_with_replay(task_id=task_id, since_seq=since_seq)
    if gap_reason is None and since_seq is not None and since_seq < result.window.oldest_sequence:
        gap_reason = "since_seq_out_of_window"
    return result, gap_reason


async def _send_ready_with_replay(
    websocket: WebSocket,
    *,
    result: EventSubscriptionResult,
    task_id: str | None,
    client_epoch: str | None,
    requested_since_seq: int | None,
    gap_reason: str | None,
) -> None:
    """下发 ``system.ready`` 及有界回放批次。

    顺序固定：先 ``system.replay_gap``（如有缺口），再 ``system.ready``（携带
    ``streamEpoch`` / ``oldestSequence`` / ``currentSequence`` /
    ``replayComplete``），最后分批直发回放事件。客户端据此检测服务重启后的
    epoch 变化，在缺口时丢弃旧 cursor 并从 SQLite 权威刷新，WebSocket 只保留
    低延迟通知职责。
    """
    window = result.window

    if gap_reason is not None:
        await websocket.send_json(
            _replay_gap_event(
                reason=gap_reason,
                task_id=task_id,
                client_epoch=client_epoch,
                window=window,
                requested_since_seq=requested_since_seq,
            )
        )

    await websocket.send_json(
        _ready_event(
            task_id=task_id,
            window=window,
            replay_complete=result.replay_complete,
        )
    )
    await _send_replay(websocket, result.replay_events)


async def _send_replay(websocket: WebSocket, replay_events: list[TaskEvent]) -> None:
    """分批直发回放事件，避免把大于订阅队列容量的回放塞进队列被 drop-oldest。"""
    for start in range(0, len(replay_events), REPLAY_BATCH_SIZE):
        chunk = replay_events[start : start + REPLAY_BATCH_SIZE]
        for evt in chunk:
            await websocket.send_json(evt.to_dict())


async def _stream_events(websocket: WebSocket, subscription: EventSubscription) -> None:
    """持续推送事件到 WebSocket（含 tick 级 coalesce + 主动断连检测）。

    每次从队列获取事件后，尝试不阻塞地排空额外堆积事件，按 type 合并后
    批量发送，减少 WS 帧数。

    并发 watcher 监听客户端断连并置位 ``disconnected``；主循环以较短间隔
    （``_DISCONNECT_POLL_SECONDS``）的 ``wait_for`` 轮询该标记，客户端关闭/网络
    中断时及时释放订阅队列，避免 socket 未优雅关闭时订阅占位过久（慢消费者 /
    max_subscribers 场景）。心跳仍按 ``WS_KEEPALIVE_SECONDS`` 发送，前端以其
    2.5 倍时长判定静默断连。

    不用 ``asyncio.wait`` 多路竞争：TestClient / anyio portal 下 ``asyncio.wait``
    在取消传播时会把 concurrent.futures.CancelledError 泄漏到 ``portal.call``，
    表现为 flaky 失败；``wait_for`` 自管内部任务取消，取消传播干净。
    """
    disconnected = asyncio.Event()

    async def _watch_disconnect() -> None:
        """持续接收并忽略非断连消息；收到断连时置位事件。"""
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    disconnected.set()
                    return
        except Exception:
            # 发送侧异常（如已断开）同样视为断连，避免 watcher 静默悬挂。
            disconnected.set()

    watcher = asyncio.create_task(_watch_disconnect())
    loop = asyncio.get_running_loop()
    last_keepalive = loop.time()
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    subscription.queue.get(),
                    timeout=_DISCONNECT_POLL_SECONDS,
                )
            except asyncio.TimeoutError:
                if disconnected.is_set():
                    raise WebSocketDisconnect()
                now = loop.time()
                if now - last_keepalive >= WS_KEEPALIVE_SECONDS:
                    await websocket.send_json(_system_event("system.keepalive"))
                    last_keepalive = now
                continue

            batch: list[TaskEvent] = [event]
            while True:
                try:
                    batch.append(subscription.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            for _ in batch:
                subscription.queue.task_done()

            coalesced = _coalesce_events(batch)
            for evt in coalesced:
                await websocket.send_json(evt.to_dict())
    except WebSocketDisconnect:
        return
    finally:
        watcher.cancel()
        await subscription.close()


def _coalesce_events(events: list[TaskEvent]) -> list[TaskEvent]:
    """白名单式合并：只对幂等可合并事件类型压缩，其余全部保留。

    可合并（白名单内的中间态事件，只有最新值有意义）：
    - task.progress, step.update, evaluator.thinking
    不可合并（离散事件，每条都必须推送给前端）：
    - step.complete, finding.added, log.append, planner_result, evaluator_result, ...
    """
    _COALESCE_TYPES = frozenset({"task.progress", "step.update", "evaluator.thinking"})
    last_idx: dict[tuple[str, str], int] = {}
    keep = [True] * len(events)
    for i, evt in enumerate(events):
        if evt.event_type not in _COALESCE_TYPES:
            continue
        key = (evt.task_id, evt.event_type)
        if key in last_idx:
            keep[last_idx[key]] = False
        last_idx[key] = i
    return [e for e, k in zip(events, keep, strict=True) if k]


def _system_event(
    event_type: str,
    task_id: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """生成系统事件。"""
    event: dict[str, Any] = {
        "eventType": event_type,
        "taskId": task_id,
        "data": {},
    }
    if message:
        event["data"]["message"] = message
    return event


def _ready_event(
    task_id: str | None,
    window: ReplayWindow,
    replay_complete: bool,
) -> dict[str, Any]:
    """生成 ``system.ready``：携带可回放窗口与回放完成标记。

    - ``streamEpoch``：本次进程的事件流纪元，重启即变化；
    - ``oldestSequence`` / ``currentSequence``：可回放窗口边界；
    - ``replayComplete``：本次回放是否无缺口地送达到客户端。
    """
    event = _system_event(
        "system.ready",
        task_id=task_id,
        message="事件订阅已建立。",
    )
    event["data"].update(
        {
            "streamEpoch": window.stream_epoch,
            "oldestSequence": window.oldest_sequence,
            "currentSequence": window.current_sequence,
            "replayComplete": replay_complete,
        }
    )
    return event


def _replay_gap_event(
    reason: str,
    task_id: str | None,
    client_epoch: str | None,
    window: ReplayWindow,
    requested_since_seq: int | None,
) -> dict[str, Any]:
    """生成 ``system.replay_gap``：显式告知客户端存在回放缺口，不要静默丢失。

    ``reason`` 取值：
    - ``epoch_changed``：服务重启后 sequence 空间不连续（客户端带旧 epoch）；
    - ``since_seq_out_of_window``：客户端请求的 sinceSeq 早于可回放窗口。
    """
    data: dict[str, Any] = {
        "reason": reason,
        "streamEpoch": window.stream_epoch,
        "oldestSequence": window.oldest_sequence,
        "currentSequence": window.current_sequence,
        "message": "事件流存在缺口，客户端应丢弃旧游标并从权威接口重新同步。",
    }
    if requested_since_seq is not None:
        data["requestedSinceSeq"] = requested_since_seq
    if client_epoch is not None:
        data["previousEpoch"] = client_epoch
    return {"eventType": "system.replay_gap", "taskId": task_id, "data": data}
