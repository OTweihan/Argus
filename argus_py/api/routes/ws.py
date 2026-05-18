"""WebSocket 实时事件路由。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from argus_py.api.dependencies import get_event_bus, get_task_service
from argus_py.core.constants import WS_KEEPALIVE_SECONDS
from argus_py.core.exceptions import TaskError
from argus_py.infra.events import EventBus, EventSubscription
from argus_py.task.service import TaskService

router = APIRouter(prefix="/ws", tags=["websocket"])


@router.websocket("/tasks/{task_id}")
async def task_events(
    websocket: WebSocket,
    task_id: str,
    event_bus: EventBus = Depends(get_event_bus),
    service: TaskService = Depends(get_task_service),
) -> None:
    """订阅单个任务的实时事件。"""
    await websocket.accept()
    try:
        # SQLite 读阻塞事件循环时 WebSocket 心跳会被拖慢，挪去线程池。
        await asyncio.to_thread(service.get_task, task_id)
    except TaskError as exc:
        await websocket.send_json(_system_event("system.error", task_id=task_id, message=str(exc)))
        await websocket.close(code=1008)
        return

    subscription = await event_bus.subscribe(task_id=task_id, replay=True)
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
    await websocket.accept()
    subscription = await event_bus.subscribe(task_id=None, replay=True)
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
        "type": event_type,
        "taskId": task_id,
        "data": {},
    }
    if message:
        event["data"]["message"] = message
    return event
