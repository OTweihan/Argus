"""WebSocket 实时事件路由。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from argus_py.api.dependencies import get_event_bus, get_task_service
from argus_py.config.server_settings import load_server_settings
from argus_py.infra.events import EventBus, EventBusSubscriberLimitError, EventSubscription
from argus_py.observability.context import run_in_thread
from argus_py.task.service import TaskService

logger = logging.getLogger(__name__)

# 服务端发心跳的间隔（秒）。前端 ws.ts 以 2.5× 此值判定断连，调整时同步更新前端。
WS_KEEPALIVE_SECONDS = 30.0

# CORS allow list 模块级缓存：避免每次 WS 连接都读磁盘 parse YAML。
# 生产容器中 server.yaml 在部署后不会变更，一次性加载即可；开发环境
# 修改 yaml 后重启进程即可刷新。
_cors_origins_cache: list[str] | None = None

router = APIRouter(prefix="/ws", tags=["websocket"])


def _parse_since_seq(websocket: WebSocket) -> int | None:
    """从 WebSocket 查询参数中提取 ``sinceSeq``（客户端重连时传入）。"""
    raw = websocket.query_params.get("sinceSeq")
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


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
    service: TaskService = Depends(get_task_service),
) -> None:
    """订阅单个任务的实时事件。"""
    if not _is_origin_allowed(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    since_seq = _parse_since_seq(websocket)
    # SQLite 读阻塞事件循环时 WebSocket 心跳会被拖慢，挪去线程池。
    if not await run_in_thread(service.task_exists, task_id):
        await websocket.send_json(
            _system_event("system.error", task_id=task_id, message=f"任务不存在：{task_id}")
        )
        await websocket.close(code=1008)
        return

    try:
        subscription = await event_bus.subscribe(task_id=task_id, replay=True, since_seq=since_seq)
    except EventBusSubscriberLimitError as exc:
        await websocket.send_json(_system_event("system.error", task_id=task_id, message=str(exc)))
        # 1013 service overload：让前端区分"系统忙，可重试"与 1008 业务拒绝。
        await websocket.close(code=1013)
        return
    await websocket.send_json(
        _system_event("system.ready", task_id=task_id, message="任务事件订阅已建立。")
    )
    await _stream_events(websocket, subscription)


@router.websocket("/tasks")
async def all_task_events(
    websocket: WebSocket,
    event_bus: EventBus = Depends(get_event_bus),
) -> None:
    """订阅所有任务的实时事件。"""
    if not _is_origin_allowed(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    since_seq = _parse_since_seq(websocket)
    try:
        subscription = await event_bus.subscribe(task_id=None, replay=True, since_seq=since_seq)
    except EventBusSubscriberLimitError as exc:
        await websocket.send_json(_system_event("system.error", message=str(exc)))
        await websocket.close(code=1013)
        return
    await websocket.send_json(_system_event("system.ready", message="全局任务事件订阅已建立。"))
    await _stream_events(websocket, subscription)


async def _stream_events(websocket: WebSocket, subscription: EventSubscription) -> None:
    """持续推送事件到 WebSocket。"""
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    subscription.queue.get(),
                    timeout=WS_KEEPALIVE_SECONDS,
                )
            except TimeoutError:
                await websocket.send_json(_system_event("system.keepalive"))
                continue

            await websocket.send_json(event.to_dict())
            subscription.queue.task_done()
    except WebSocketDisconnect:
        return
    finally:
        await subscription.close()


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
