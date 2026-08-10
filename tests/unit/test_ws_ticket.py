"""WebSocket 短时 ticket：签发 / 消费 / 过期 / 篡改 / 单次使用。

启用 API Token 鉴权时，浏览器先在 HTTP 层用 Bearer 换取短时单次 ticket，
再用 ``?token=<ticket>`` 建立 WebSocket；长期 Token 不再进入 WS URL（避免
进入反代/接入日志）。本文件验证签发链路、HMAC 签名、TTL 与单次使用语义。
"""

from __future__ import annotations

import base64
import time

import pytest
from argus_py.api import auth as auth_module
from argus_py.api.auth import (
    WS_TICKET_TTL_SECONDS,
    AuthTokenMiddleware,
    WebSocketTicketError,
    WebSocketTicketIssuer,
)
from argus_py.api.routes.ws import _consume_ws_ticket, issue_ws_token
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

TOKEN = "long-lived-secret-token"


def _make_ticket_app() -> FastAPI:
    """构造带 AuthTokenMiddleware + ticket 路由 + 单测 WS 端点的应用。"""
    app = FastAPI()

    @app.post("/argus/api/ws/token")
    async def _issue(request: Request) -> dict:
        return await issue_ws_token(request)

    @app.websocket("/argus/api/ws/tasks")
    async def _ws(websocket: WebSocket) -> None:
        # 复刻真实路由的 ticket 扣减（连接被接受前消费）。
        if not _consume_ws_ticket(websocket):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_text("ok")
        await websocket.close()

    app.add_middleware(AuthTokenMiddleware, token=TOKEN)
    return app


class TestTicketIssuer:
    def test_issue_returns_opaque_ticket(self) -> None:
        issuer = WebSocketTicketIssuer(TOKEN)
        ticket = issuer.issue()
        assert isinstance(ticket, str)
        assert ticket
        # base64url + 无填充歧义：可被解析回原字节
        raw = base64.urlsafe_b64decode(ticket.encode("ascii"))
        assert len(raw) > 8 + auth_module.WS_TICKET_NONCE_BYTES
        assert len(raw) == 8 + auth_module.WS_TICKET_NONCE_BYTES + 32

    def test_consume_single_use(self) -> None:
        issuer = WebSocketTicketIssuer(TOKEN)
        ticket = issuer.issue()
        issuer.consume(ticket)  # 首次通过
        with pytest.raises(WebSocketTicketError):
            issuer.consume(ticket)  # 二次使用被拒

    def test_is_valid_does_not_consume(self) -> None:
        issuer = WebSocketTicketIssuer(TOKEN)
        ticket = issuer.issue()
        assert issuer.is_valid(ticket) is True
        # is_valid 不扣减：随后 consume 仍应成功
        issuer.consume(ticket)

    def test_tampered_ticket_rejected(self) -> None:
        issuer = WebSocketTicketIssuer(TOKEN)
        ticket = issuer.issue()
        # 翻转 signature 部分的一个字节
        raw = bytearray(base64.urlsafe_b64decode(ticket.encode("ascii")))
        raw[-1] ^= 0xFF
        tampered = base64.urlsafe_b64encode(bytes(raw)).decode("ascii")
        with pytest.raises(WebSocketTicketError):
            issuer.consume(tampered)

    def test_expired_ticket_rejected(self, monkeypatch) -> None:
        issuer = WebSocketTicketIssuer(TOKEN)
        ticket = issuer.issue()
        real = time.monotonic
        monkeypatch.setattr(
            auth_module.time, "monotonic", lambda: real() + WS_TICKET_TTL_SECONDS + 1
        )
        with pytest.raises(WebSocketTicketError):
            issuer.consume(ticket)

    def test_cross_secret_rejected(self) -> None:
        issuer_a = WebSocketTicketIssuer("secret-a")
        issuer_b = WebSocketTicketIssuer("secret-b")
        with pytest.raises(WebSocketTicketError):
            issuer_b.consume(issuer_a.issue())


class TestTicketHttpFlow:
    def test_token_route_requires_bearer(self) -> None:
        client = TestClient(_make_ticket_app())
        resp = client.post("/argus/api/ws/token")
        assert resp.status_code == 401

    def test_issue_then_connect_with_ticket(self) -> None:
        client = TestClient(_make_ticket_app())
        resp = client.post("/argus/api/ws/token", headers={"Authorization": f"Bearer {TOKEN}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["singleUse"] is True
        assert body["expiresIn"] == WS_TICKET_TTL_SECONDS
        ticket = body["token"]
        assert ticket

        with client.websocket_connect(f"/argus/api/ws/tasks?token={ticket}") as ws:
            assert ws.receive_text() == "ok"

    def test_ticket_is_single_use(self) -> None:
        client = TestClient(_make_ticket_app())
        resp = client.post("/argus/api/ws/token", headers={"Authorization": f"Bearer {TOKEN}"})
        ticket = resp.json()["token"]

        with client.websocket_connect(f"/argus/api/ws/tasks?token={ticket}") as ws:
            assert ws.receive_text() == "ok"

        # 同一 ticket 第二次连接：中间件 is_valid 已因 nonce 入已用集合而拒绝。
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/argus/api/ws/tasks?token={ticket}"):
                pass

    def test_long_token_query_is_rejected(self) -> None:
        """长期 Token 不再允许出现在 query，避免进入反代/接入日志。"""
        client = TestClient(_make_ticket_app())
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/argus/api/ws/tasks?token={TOKEN}"):
                pass

    def test_long_token_bearer_header_still_works(self) -> None:
        """CLI / 服务器到服务器调用可通过 Authorization 头使用长期 Token。"""
        client = TestClient(_make_ticket_app())
        with client.websocket_connect(
            "/argus/api/ws/tasks", headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            assert ws.receive_text() == "ok"

    def test_missing_token_rejected(self) -> None:
        client = TestClient(_make_ticket_app())
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/argus/api/ws/tasks"):
                pass
