"""可选 API Token 鉴权中间件 + WebSocket 短时 ticket。

私网部署里"反代套 SSO / Basic Auth"是最佳实践，但反代不总能落地。
此中间件提供一个**最小可行**的 token 鉴权选项：

- 默认禁用（``ARGUS_API_TOKEN`` 未设置时不挂载，零行为变化）；
- 启用后只保护 ``/argus/api/*`` 与 ``/ws/*``，不保护 ``/health`` 和静态资源，
  因为后者要么由反代/Compose 直接探测，要么是浏览器加载首页 HTML 无法带 header；
- HTTP 走 ``Authorization: Bearer <token>``；WebSocket 的长期 Token 只接受
  ``Authorization`` 头，浏览器 query 只接受短时单次 ticket；
- 使用 ``hmac.compare_digest`` 防止时序侧信道。

WebSocket 长期 Token 放进 query string 会进入反代/接入日志。因此启用鉴权时，
浏览器先在 HTTP 层用 Bearer Token 换取**短时、单次** WebSocket ticket，再带
``?token=<ticket>`` 连接；长期 Token 不再出现在 WS URL 中。ticket 由 HMAC
签名、带签发时间与随机 nonce，默认 30 秒内有效、每个 ticket 只能使用一次。

需要更强的访问控制（按用户/角色、单点登录、Token 轮换）请通过反代外接 SSO，
不要把这套逻辑做厚。
"""

from __future__ import annotations

import base64
import binascii
import hmac
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from argus_py.api.errors import error_response

logger = logging.getLogger(__name__)

# 启用 token 时的默认保护前缀。``/health`` 故意不在此列：反代健康检查、
# docker compose healthcheck、k8s liveness 都依赖匿名 GET。
DEFAULT_PROTECTED_PREFIXES: tuple[str, ...] = ("/argus/api/", "/ws/")

# WebSocket ticket 有效期（秒）。远大于前端"先请求 ticket 再建 WS"的往返延迟，
# 但远小于任何会被日志/缓存长期保留的时间窗。
WS_TICKET_TTL_SECONDS = 30
# ticket 随机 nonce 长度（字节）。
WS_TICKET_NONCE_BYTES = 16


class WebSocketTicketError(Exception):
    """WebSocket ticket 校验失败（过期、重复使用或签名无效）。"""


class WebSocketTicketIssuer:
    """HMAC 签名的短时 WebSocket ticket。

    每个 ticket 绑定签发时间戳与随机 nonce：服务端记录已消费的 nonce，
    保证"单次使用"；签名密钥复用 API Token，因此只有启用鉴权时才可能签发。
    """

    def __init__(
        self,
        secret: str,
        *,
        ttl_seconds: int = WS_TICKET_TTL_SECONDS,
    ) -> None:
        if not secret:
            raise ValueError("WebSocketTicketIssuer 要求非空 secret")
        self._secret = secret.encode("utf-8")
        self._ttl = max(1, int(ttl_seconds))
        # 已消费 nonce 的最近时间戳（用于驱逐过期条目，防止集合无限增长）。
        self._used: dict[bytes, float] = {}
        # 允许的时钟偏差：ticket 在签发方与校验方同进程签发/消费，
        # 只留少量余量容纳并发调度延迟。
        self._clock_skew = 5.0

    def issue(self) -> str:
        """签发一个新的短时 ticket。"""
        # 单调时钟的整数秒：足够覆盖 TTL（30s）比较；签发方与消费方同进程，
        # 不需要高精度时间戳。
        timestamp = int(time.monotonic())
        nonce = os.urandom(WS_TICKET_NONCE_BYTES)
        payload = timestamp.to_bytes(8, "big") + nonce
        signature = hmac.new(self._secret, payload, "sha256").digest()
        return base64.urlsafe_b64encode(payload + signature).decode("ascii")

    def is_valid(self, ticket: str) -> bool:
        """非消费式校验：签名有效、未过期且未被使用。

        供中间件对 WebSocket 连接做轻量放行判断；真正"单次使用"的扣减在
        路由层调用 ``consume`` 完成，避免握手被后续校验拒绝时白白烧掉 ticket。
        """
        try:
            self._verify(ticket)
        except WebSocketTicketError:
            return False
        return True

    def consume(self, ticket: str) -> None:
        """校验并消费一个 ticket；失败抛 WebSocketTicketError。

        使用时间戳的单调时钟，不依赖 wall clock 回拨。消费成功后 nonce 进入
        已用集合，直到其对应时间戳超出 TTL 才会被清理。
        """
        _, nonce = self._verify(ticket)
        # 单次使用：同一 nonce 重复消费直接拒绝。
        if nonce in self._used:
            raise WebSocketTicketError("ticket 已被使用")
        self._used[nonce] = time.monotonic()

        # 惰性清理早于 TTL 的已用条目，避免并发链接长期积累。
        cutoff = time.monotonic() - self._ttl
        expired = [n for n, ts in self._used.items() if ts < cutoff]
        for n in expired:
            self._used.pop(n, None)

    def _verify(self, ticket: str) -> tuple[bytes, bytes]:
        """解析并验证 ticket，返回 (timestamp_bytes, nonce)。失败抛异常。"""
        try:
            raw = base64.urlsafe_b64decode(ticket.encode("ascii"))
        except (binascii.Error, UnicodeEncodeError) as exc:
            raise WebSocketTicketError("ticket 格式无效") from exc
        if len(raw) != 8 + WS_TICKET_NONCE_BYTES + 32:
            raise WebSocketTicketError("ticket 长度无效")

        timestamp = int.from_bytes(raw[:8], "big")
        nonce = raw[8 : 8 + WS_TICKET_NONCE_BYTES]
        signature = raw[8 + WS_TICKET_NONCE_BYTES :]

        expected = hmac.new(self._secret, raw[: 8 + WS_TICKET_NONCE_BYTES], "sha256").digest()
        if not hmac.compare_digest(signature, expected):
            raise WebSocketTicketError("ticket 签名无效")

        age = time.monotonic() - timestamp
        if age < -self._clock_skew:
            raise WebSocketTicketError("ticket 尚未生效")
        if age > self._ttl:
            raise WebSocketTicketError("ticket 已过期")
        return raw[:8], nonce


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
        self._ticket_issuer = WebSocketTicketIssuer(token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if scope_type not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "") or ""
        if not path.startswith(self._protected_prefixes):
            await self._app(scope, receive, send)
            return

        if scope_type == "http":
            # HTTP 只接受长期 Token（Bearer 头）。
            provided = self._extract_bearer_token(scope)
            if provided is None:
                await self._reject(scope, receive, send)
                return
            if not hmac.compare_digest(provided, self._token):
                await self._reject(scope, receive, send)
                return
        else:
            # 长期 Token 仅允许经 Authorization 头传递，避免 query string 进入
            # 反代/接入日志；浏览器 query 只接受短时单次 ticket。
            bearer = self._extract_bearer_token(scope)
            ticket = None if bearer is not None else self._extract_ws_query_token(scope)
            if bearer is not None and hmac.compare_digest(bearer, self._token):
                scope.setdefault("state", {})["argus_ws_auth"] = "token"
            elif ticket is not None and self._ticket_issuer.is_valid(ticket):
                scope.setdefault("state", {})["argus_ws_auth"] = "ticket"
                scope.setdefault("state", {})["argus_ws_ticket"] = ticket
            else:
                await self._reject(scope, receive, send)
                return

        await self._app(scope, receive, send)

    @staticmethod
    def _extract_bearer_token(scope: Scope) -> str | None:
        """从 Authorization 头读取长期 Token。"""
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

    @staticmethod
    def _extract_ws_query_token(scope: Scope) -> str | None:
        """从 WebSocket query 读取短时 ticket；不承载长期 Token。"""
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


def issue_ws_ticket(app: ASGIApp) -> str:
    """从已挂载中间件签发一个短时 WebSocket ticket。

    供 ``/argus/api/ws/token`` 路由使用：浏览器用 Bearer Token 换取
    仅用于 WebSocket query 的一次性 ticket。中间件未挂载时抛出
    ``ValueError``（未启用鉴权就不存在 ticket 语义）。
    """
    middleware = _find_ticket_issuer(app)
    return middleware.issue()


def consume_ws_ticket(app: ASGIApp, token: str) -> None:
    """校验并消费一个 WebSocket ticket；失败抛 ``WebSocketTicketError``。

    供 ``/argus/api/ws/*`` 路由使用：ticket 校验通过后连接才被接受。
    """
    middleware = _find_ticket_issuer(app)
    middleware.consume(token)


def _find_ticket_issuer(app: ASGIApp) -> WebSocketTicketIssuer:
    """沿 ASGI 中间件链查找已挂载的 ``AuthTokenMiddleware``。

    路由从 ``request.app`` 拿到应用实例；中间件实际挂在
    ``app.middleware_stack``（Starlette 的 ``_middleware_wrapper`` 链）上，
    每层都有 ``.app`` 指向更内层的应用，逐层下钻即可找到真实的
    ``AuthTokenMiddleware`` 实例。
    """
    candidate: Any = getattr(app, "middleware_stack", None) or app
    for _ in range(64):
        if candidate is None:
            break
        if isinstance(candidate, AuthTokenMiddleware):
            return candidate._ticket_issuer
        candidate = getattr(candidate, "app", None)
    raise ValueError("WebSocket ticket 需要先启用 API Token 鉴权（ARGUS_API_TOKEN）")


def build_auth_middleware(
    app: ASGIApp,
    token: str | None,
    protected_prefixes: tuple[str, ...] = DEFAULT_PROTECTED_PREFIXES,
) -> Callable[[Scope, Receive, Send], Awaitable[Any]] | None:
    """工厂方法：token 为空时返回 None（调用方据此决定是否挂载）。"""
    if not token:
        return None
    return AuthTokenMiddleware(app, token=token, protected_prefixes=protected_prefixes)
