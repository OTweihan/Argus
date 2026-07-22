"""可选 API Token 鉴权中间件。

私网部署里"反代套 SSO / Basic Auth"是最佳实践，但反代不总能落地。
此中间件提供一个**最小可行**的 token 鉴权选项：

- 默认禁用（``ARGUS_API_TOKEN`` 未设置时不挂载，零行为变化）；
- 启用后只保护 ``/argus/api/*`` 与 ``/ws/*``，不保护 ``/health`` 和静态资源，
  因为后者要么由反代/Compose 直接探测，要么是浏览器加载首页 HTML 无法带 header；
- HTTP 走 ``Authorization: Bearer <token>``，WebSocket 走 query ``?token=<token>``
  （浏览器原生 WebSocket 不支持自定义 header）；
- 使用 ``hmac.compare_digest`` 防止时序侧信道。

需要更强的访问控制（按用户/角色、单点登录、Token 轮换）请通过反代外接 SSO，
不要把这套逻辑做厚。
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from argus_py.api.errors import error_response

logger = logging.getLogger(__name__)

# 启用 token 时的默认保护前缀。``/health`` 故意不在此列：反代健康检查、
# docker compose healthcheck、k8s liveness 都依赖匿名 GET。
DEFAULT_PROTECTED_PREFIXES: tuple[str, ...] = ("/argus/api/", "/ws/")


class AuthTokenMiddleware:
    """ASGI 中间件：对受保护路径强制 Bearer Token / query token 校验。

    用纯 ASGI 实现（不继承 ``BaseHTTPMiddleware``）是因为后者无法处理
    ``type == "websocket"`` 的 scope；而 WebSocket 鉴权对运维同样重要——
    LLM trace 推送也走 WS，如果只保护 HTTP 等于把后门留给 WS。
    """

    def __init__(
        self,
        app: ASGIApp,
        token: str,
        protected_prefixes: tuple[str, ...] = DEFAULT_PROTECTED_PREFIXES,
    ) -> None:
        if not token:
            raise ValueError("AuthTokenMiddleware 要求非空 token")
        self._app = app
        self._token = token
        self._protected_prefixes = protected_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if scope_type not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "") or ""
        if not path.startswith(self._protected_prefixes):
            await self._app(scope, receive, send)
            return

        provided = self._extract_token(scope)
        if provided is None or not hmac.compare_digest(provided, self._token):
            await self._reject(scope, receive, send)
            return

        await self._app(scope, receive, send)

    def _extract_token(self, scope: Scope) -> str | None:
        """从 HTTP Authorization 头或 WebSocket query 字符串读取 token。"""
        scope_type = scope.get("type")
        if scope_type == "http":
            headers = dict(scope.get("headers") or [])
            raw = headers.get(b"authorization")
            if not raw:
                return None
            try:
                decoded = raw.decode("latin-1")
            except UnicodeDecodeError:
                return None
            prefix = "Bearer "
            if not decoded.startswith(prefix):
                return None
            token = decoded[len(prefix) :].strip()
            return token or None
        if scope_type == "websocket":
            # Authorization 头优先：CLI / 服务器到服务器调用可用
            headers = dict(scope.get("headers") or [])
            raw = headers.get(b"authorization")
            if raw:
                try:
                    decoded = raw.decode("latin-1")
                    if decoded.startswith("Bearer "):
                        return decoded[7:].strip() or None
                except UnicodeDecodeError:
                    pass
            # 浏览器 WS 无法带 header → 退回 query string
            qs: bytes = scope.get("query_string", b"") or b""
            try:
                params = qs.decode("latin-1").split("&")
            except UnicodeDecodeError:
                return None
            for kv in params:
                if not kv:
                    continue
                key, _, value = kv.partition("=")
                if key == "token":
                    return _url_unquote(value) or None
            return None
        return None

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")

        if scope_type == "http":
            response: Response = error_response(
                "UNAUTHORIZED",
                "需要有效的 API Token。",
                401,
                headers={"WWW-Authenticate": 'Bearer realm="argus"'},
            )
            await response(scope, receive, send)
            return

        # WebSocket：尚未 accept 时直接 close；策略违例对应 1008
        await send({"type": "websocket.close", "code": 1008})


def _url_unquote(value: str) -> str:
    """轻量 URL decode：避免 import urllib 增加冷启动；只处理 + 与 %xx。"""
    from urllib.parse import unquote_plus

    return unquote_plus(value)


def build_auth_middleware(
    app: ASGIApp,
    token: str | None,
    protected_prefixes: tuple[str, ...] = DEFAULT_PROTECTED_PREFIXES,
) -> Callable[[Scope, Receive, Send], Awaitable[Any]] | None:
    """工厂方法：token 为空时返回 None（调用方据此决定是否挂载）。"""
    if not token:
        return None
    return AuthTokenMiddleware(app, token=token, protected_prefixes=protected_prefixes)
