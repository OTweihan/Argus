"""WS 路由回放/纪元契约测试（O-05）。

通过 TestClient 驱动真实 ``ws`` 路由：
- system.ready 携带 streamEpoch / oldestSequence / currentSequence / replayComplete
- history_limit > subscriber_queue_size 时回放不丢事件（有界直发）
- epoch 不匹配（服务重启）→ system.replay_gap(epoch_changed) + 完整回放
- sinceSeq 早于可回放窗口 → system.replay_gap(since_seq_out_of_window)
- sinceSeq 在窗口内 → 部分回放、无 gap
- 客户端断连后订阅及时释放
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from argus_py.api.dependencies import get_event_bus, get_task_read_service
from argus_py.api.routes import ws as ws_module
from argus_py.api.routes.ws import router as ws_router
from argus_py.infra.events import EventBus
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_PREFIX = "/argus/api"
pytestmark = [pytest.mark.integration]


def _build_app(bus: EventBus) -> FastAPI:
    """构造仅挂载 ws 路由的测试应用，override EventBus / TaskReadService。"""
    app = FastAPI(title="WS Replay Gap Test")
    app.include_router(ws_router, prefix=API_PREFIX)
    reader = SimpleNamespace(task_exists=lambda _task_id: True)
    app.dependency_overrides[get_event_bus] = lambda: bus
    app.dependency_overrides[get_task_read_service] = lambda: reader
    return app


def _connect(
    client: TestClient,
    path: str = "/ws/tasks",
    **params: str,
) -> Any:
    """建立 WebSocket 连接并返回会话。"""
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{API_PREFIX}{path}" + (f"?{query}" if query else "")
    return client.websocket_connect(url)


@pytest.fixture(autouse=True)
def _allow_all_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    """TestClient 无 Origin 头时本就放行；这里显式置 * 排除 CORS 干扰。"""
    monkeypatch.setattr(ws_module, "_cors_origins_cache", ["*"])


class TestReadyWithReplay:
    def test_ready_carries_window_and_full_replay_when_history_gt_queue(self) -> None:
        """history_limit=200 > subscriber_queue_size=10：150 条全部回放，无 drop。"""
        bus = EventBus(history_limit=200, subscriber_queue_size=10)
        for i in range(1, 151):
            bus.publish("task.step", "tk-1", {"i": i})
        client = TestClient(_build_app(bus))

        with _connect(client) as ws:
            ready = ws.receive_json()
            assert ready["eventType"] == "system.ready"
            data = ready["data"]
            assert data["streamEpoch"] == bus.stream_epoch
            assert data["oldestSequence"] == 1
            assert data["currentSequence"] == 150
            assert data["replayComplete"] is True

            # 回放批次直发：150 条全部按序送达，不因队列容量 10 而丢事件。
            sequences: list[int] = []
            for _ in range(150):
                event = ws.receive_json()
                assert event["eventType"] == "task.step"
                sequences.append(event["sequence"])
            assert sequences == list(range(1, 151))

    def test_in_window_partial_replay_no_gap(self) -> None:
        """sinceSeq 在可回放窗口内且 epoch 匹配：部分回放、无 gap。"""
        bus = EventBus(history_limit=20, subscriber_queue_size=5)
        for i in range(1, 6):
            bus.publish("task.step", "tk-1", {"i": i})
        client = TestClient(_build_app(bus))

        with _connect(
            client,
            sinceSeq="3",
            epoch=bus.stream_epoch,
        ) as ws:
            ready = ws.receive_json()
            assert ready["eventType"] == "system.ready"
            # 无 gap：下一条就是回放事件，而不是 replay_gap。
            replay = [ws.receive_json() for _ in range(2)]
            assert [e["sequence"] for e in replay] == [4, 5]


class TestReplayGap:
    def test_epoch_mismatch_sends_gap_and_replays_full_history(self) -> None:
        """客户端带旧纪元（服务重启）：epoch_changed + 完整回放。"""
        bus = EventBus(history_limit=20, subscriber_queue_size=5)
        for i in range(1, 4):
            bus.publish("task.step", "tk-1", {"i": i})
        client = TestClient(_build_app(bus))

        # 旧纪元高 sinceSeq 属于已不存在的序列空间：服务端应丢弃它并完整回放。
        with _connect(
            client,
            epoch="ev-stale-process",
            sinceSeq="999",
        ) as ws:
            gap = ws.receive_json()
            assert gap["eventType"] == "system.replay_gap"
            gap_data = gap["data"]
            assert gap_data["reason"] == "epoch_changed"
            assert gap_data["previousEpoch"] == "ev-stale-process"
            assert gap_data["streamEpoch"] == bus.stream_epoch

            ready = ws.receive_json()
            assert ready["eventType"] == "system.ready"
            assert ready["data"]["streamEpoch"] == bus.stream_epoch

            # 完整回放（丢弃旧 sinceSeq 999）
            replay = [ws.receive_json() for _ in range(3)]
            assert [e["sequence"] for e in replay] == [1, 2, 3]

    def test_since_seq_out_of_window_sends_gap(self) -> None:
        """sinceSeq 早于可回放窗口：since_seq_out_of_window + 回放全部可回放事件。"""
        bus = EventBus(history_limit=3)
        for i in range(1, 6):
            bus.publish("task.step", "tk-1", {"i": i})
        client = TestClient(_build_app(bus))

        # history_limit=3 只保留 seq 3,4,5；sinceSeq=0 早于 oldest=3。
        with _connect(client, sinceSeq="0") as ws:
            gap = ws.receive_json()
            assert gap["eventType"] == "system.replay_gap"
            gap_data = gap["data"]
            assert gap_data["reason"] == "since_seq_out_of_window"
            assert gap_data["requestedSinceSeq"] == 0
            assert gap_data["oldestSequence"] == 3
            assert gap_data["currentSequence"] == 5

            ready = ws.receive_json()
            assert ready["eventType"] == "system.ready"
            assert ready["data"]["oldestSequence"] == 3

            replay = [ws.receive_json() for _ in range(3)]
            assert [e["sequence"] for e in replay] == [3, 4, 5]


class TestTaskScopedEndpoint:
    def test_task_scoped_ready_marks_task_id(self) -> None:
        """任务级端点：system.ready 携带 taskId，且只回放该任务事件。"""
        bus = EventBus(history_limit=20, subscriber_queue_size=5)
        bus.publish("task.step", "tk-1", {"i": 1})
        bus.publish("task.step", "tk-2", {"i": 2})
        client = TestClient(_build_app(bus))

        with _connect(client, path="/ws/tasks/tk-1") as ws:
            ready = ws.receive_json()
            assert ready["eventType"] == "system.ready"
            assert ready["taskId"] == "tk-1"

            replay = ws.receive_json()
            assert replay["taskId"] == "tk-1"
            assert replay["sequence"] == 1


class TestDisconnectRelease:
    def test_subscription_released_on_client_disconnect(self) -> None:
        """客户端优雅关闭后订阅队列及时释放，不占位过久。

        with 退出 → TestClient 发送 websocket.disconnect → watcher 收到并置位
        → 主循环短轮询检测到 → 关闭订阅。TestClient 的 __exit__ 会等待应用
        协程结束（fut.result），因此退出时订阅应已释放；这里仍加轮询兜底。
        """
        bus = EventBus(history_limit=20, subscriber_queue_size=5)
        client = TestClient(_build_app(bus))

        with _connect(client) as ws:
            ready = ws.receive_json()
            assert ready["eventType"] == "system.ready"
            assert bus.metrics()["global_subscribers"] == 1

        deadline = time.monotonic() + 5.0
        while bus.metrics()["global_subscribers"] != 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert bus.metrics()["global_subscribers"] == 0

    def test_subscription_released_on_task_scoped_disconnect(self) -> None:
        """任务级订阅在客户端断开后同样释放。"""
        bus = EventBus(history_limit=20, subscriber_queue_size=5)
        client = TestClient(_build_app(bus))

        with _connect(client, path="/ws/tasks/tk-1") as ws:
            ready = ws.receive_json()
            assert ready["eventType"] == "system.ready"
            assert bus.metrics()["task_subscribers"] == 1

        deadline = time.monotonic() + 5.0
        while bus.metrics()["task_subscribers"] != 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert bus.metrics()["task_subscribers"] == 0
