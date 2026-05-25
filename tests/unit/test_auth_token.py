"""可选 API Token 鉴权中间件单测。"""

from __future__ import annotations

import pytest
from argus_py.api.auth import (
    DEFAULT_PROTECTED_PREFIXES,
    AuthTokenMiddleware,
    build_auth_middleware,
)
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def _make_app(token: str) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthTokenMiddleware, token=token)

    @app.get("/argus/api/tasks")
    def _list() -> dict[str, str]:
        return {"ok": "1"}

    @app.get("/health")
    def _health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def _index() -> dict[str, str]:
        return {"page": "spa"}

    @app.websocket("/ws/tasks")
    async def _ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("pong")
        await websocket.close()

    return app


class TestEmptyTokenRejected:
    def test_constructor_rejects_empty_token(self) -> None:
        app = FastAPI()
        with pytest.raises(ValueError):
            AuthTokenMiddleware(app, token="")

    def test_build_returns_none_when_token_empty(self) -> None:
        app = FastAPI()
        assert build_auth_middleware(app, None) is None
        assert build_auth_middleware(app, "") is None

    def test_build_returns_instance_when_token_set(self) -> None:
        app = FastAPI()
        mw = build_auth_middleware(app, "abc")
        assert isinstance(mw, AuthTokenMiddleware)


class TestHttpProtection:
    def test_protected_path_requires_token(self) -> None:
        client = TestClient(_make_app("secret-123"))
        resp = client.get("/argus/api/tasks")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"
        assert resp.headers.get("www-authenticate", "").startswith("Bearer")

    def test_valid_bearer_token_allowed(self) -> None:
        client = TestClient(_make_app("secret-123"))
        resp = client.get("/argus/api/tasks", headers={"Authorization": "Bearer secret-123"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": "1"}

    def test_wrong_token_rejected(self) -> None:
        client = TestClient(_make_app("secret-123"))
        resp = client.get("/argus/api/tasks", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_malformed_authorization_rejected(self) -> None:
        client = TestClient(_make_app("secret-123"))
        for bad in ("Basic dXNlcjpwd2Q=", "Bearer", "Bearer ", "secret-123"):
            resp = client.get("/argus/api/tasks", headers={"Authorization": bad})
            assert resp.status_code == 401, f"bad header `{bad}` should 401"

    def test_health_path_not_protected(self) -> None:
        client = TestClient(_make_app("secret-123"))
        assert client.get("/health").status_code == 200

    def test_root_static_path_not_protected(self) -> None:
        """SPA 根路径不需要 token（浏览器无法在 HTML 加载请求里带 Bearer）。"""
        client = TestClient(_make_app("secret-123"))
        assert client.get("/").status_code == 200

    def test_protected_prefixes_match_only_segment_start(self) -> None:
        """前缀按字符串 startswith 比较 → /argus/api 才命中，/argus/apicover 不命中。"""
        app = FastAPI()
        app.add_middleware(AuthTokenMiddleware, token="t")

        @app.get("/apicover")
        def _decoy() -> dict[str, str]:
            return {"ok": "decoy"}

        client = TestClient(app)
        assert client.get("/apicover").status_code == 200


class TestWebSocketProtection:
    def test_ws_query_token_allowed(self) -> None:
        client = TestClient(_make_app("ws-secret"))
        with client.websocket_connect("/ws/tasks?token=ws-secret") as ws:
            assert ws.receive_text() == "pong"

    def test_ws_url_encoded_token_allowed(self) -> None:
        client = TestClient(_make_app("ws sec+ret"))
        with client.websocket_connect("/ws/tasks?token=ws+sec%2Bret") as ws:
            assert ws.receive_text() == "pong"

    def test_ws_missing_token_rejected(self) -> None:
        client = TestClient(_make_app("ws-secret"))
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/tasks"):
                pass

    def test_ws_wrong_token_rejected(self) -> None:
        client = TestClient(_make_app("ws-secret"))
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/tasks?token=wrong"):
                pass

    def test_ws_bearer_header_also_works(self) -> None:
        """允许服务器到服务器调用走 Authorization 头（非浏览器场景）。"""
        client = TestClient(_make_app("ws-secret"))
        with client.websocket_connect(
            "/ws/tasks", headers={"Authorization": "Bearer ws-secret"}
        ) as ws:
            assert ws.receive_text() == "pong"


def test_default_protected_prefixes_are_argus_api_and_ws() -> None:
    assert DEFAULT_PROTECTED_PREFIXES == ("/argus/api/", "/ws/")
