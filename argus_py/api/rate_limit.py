"""进程内令牌桶限流。

私网部署的限流目的不是"防外部攻击"（反代/防火墙已经在外层兜底），而是：

- 防止内部脚本失控（写了 ``while True: create_task(...)``）拖垮 LLM 配额
- 防止开发自测时反复点按钮造成 SQLite 锁竞争
- 给慢 LLM 端点一个明确的回退信号（HTTP 429 + Retry-After）

实现采用最朴素的进程内令牌桶：

- 容量 ``capacity`` = ``burst``；初始满桶
- 速率 ``refill_per_sec`` = ``requests_per_minute / 60``
- 每个 ``(client_host, rule.name)`` 独立桶

不引入新依赖（slowapi、aiolimiter 等）出于两点考虑：

1. Argus 强制单 worker（见 ``serve.py`` 多 worker 拒启护栏），进程内状态足够；
2. 限流是兜底机制，被限期间整段服务降级也可接受。

若未来要支持多 worker / 反向代理后多实例，需要切换到 Redis 之类的共享后端。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# 默认 key 抽取使用的反代 IP 头：仅在 settings 显式开启时启用，
# 避免相信非托管的客户端伪造头。
_FORWARDED_FOR_HEADER = "x-forwarded-for"


@dataclass(frozen=True)
class RateLimitRule:
    """一条限流规则。

    Attributes:
        name: 规则名，用于桶 key 与日志/指标，独立于 path（path 可能含通配）。
        method: HTTP 方法（POST/PUT/DELETE/...），大写比较。
        path_pattern: 路径模板，``*`` 匹配一个 segment（不含 ``/``）。
            例：``"/tasks"`` 精确，``"/tasks/*/start"`` 匹配 ``/tasks/<id>/start``。
        capacity: 令牌桶容量（突发上限）。
        refill_per_sec: 每秒补充令牌数（持续速率）。
    """

    name: str
    method: str
    path_pattern: str
    capacity: float
    refill_per_sec: float
    _regex: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # path_pattern → regex：'*' 替换为 [^/]+，其它字符 escape。
        parts = self.path_pattern.split("*")
        escaped = "[^/]+".join(re.escape(p) for p in parts)
        regex = re.compile(f"^{escaped}$")
        # frozen dataclass，绕过 __setattr__
        object.__setattr__(self, "_regex", regex)

    def matches(self, method: str, path: str) -> bool:
        return method.upper() == self.method.upper() and bool(self._regex.match(path))


class TokenBucketLimiter:
    """进程内令牌桶。线程安全。

    每个 key 对应一个独立桶（tokens, last_refill_ts）。桶按需懒创建；
    长期不活跃的 key 由 ``purge_idle()`` 清理（避免 dict 无限增长）。
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = threading.Lock()

    def try_acquire(
        self, key: tuple[str, str], capacity: float, refill_per_sec: float
    ) -> tuple[bool, float]:
        """尝试取走 1 个令牌。返回 (允许通过, 距离下个令牌可用的等待秒数)。"""
        if capacity <= 0 or refill_per_sec <= 0:
            return True, 0.0
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (capacity, now))
            tokens = min(capacity, tokens + (now - last) * refill_per_sec)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True, 0.0
            wait = (1.0 - tokens) / refill_per_sec
            self._buckets[key] = (tokens, now)
            return False, wait

    def purge_idle(self, idle_seconds: float = 600.0) -> int:
        """删除超过 ``idle_seconds`` 未访问的桶，返回清理数量。"""
        threshold = time.monotonic() - idle_seconds
        with self._lock:
            stale = [k for k, (_, last) in self._buckets.items() if last < threshold]
            for k in stale:
                self._buckets.pop(k, None)
        return len(stale)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"bucket_count": len(self._buckets)}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """按规则匹配请求并消耗令牌。命中限流返回 429 + Retry-After。

    匹配顺序：按 ``rules`` 列表顺序，**只命中第一条**。配置时把更精确的规则放
    前面（如 ``/tasks/*/start`` 在 ``/tasks`` 前面）。

    key 由 ``(client_id, rule.name)`` 组成。``client_id`` 取自
    ``request.client.host``；当 ``trust_forwarded=True`` 时优先用
    ``X-Forwarded-For`` 第一个 IP（仅在 Argus 后端有可信反代时启用）。
    """

    def __init__(
        self,
        app: ASGIApp,
        limiter: TokenBucketLimiter,
        rules: list[RateLimitRule],
        trust_forwarded: bool = False,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._rules = rules
        self._trust_forwarded = trust_forwarded

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path
        method = request.method
        rule = self._match(method, path)
        if rule is None:
            return await call_next(request)

        client = self._client_id(request)
        allowed, wait = self._limiter.try_acquire(
            (client, rule.name), rule.capacity, rule.refill_per_sec
        )
        if not allowed:
            retry_after = max(1, int(wait + 0.999))
            logger.warning(
                "限流命中：client=%s rule=%s method=%s path=%s retry_after=%ds",
                client,
                rule.name,
                method,
                path,
                retry_after,
            )
            return _rate_limited_response(rule.name, retry_after)
        return await call_next(request)

    def _match(self, method: str, path: str) -> RateLimitRule | None:
        for rule in self._rules:
            if rule.matches(method, path):
                return rule
        return None

    def _client_id(self, request: Request) -> str:
        if self._trust_forwarded:
            forwarded = request.headers.get(_FORWARDED_FOR_HEADER)
            if forwarded:
                # X-Forwarded-For: client, proxy1, proxy2 → 取第一个非空
                first = forwarded.split(",")[0].strip()
                if first:
                    return first
        if request.client is not None:
            return request.client.host or "unknown"
        return "unknown"


def _rate_limited_response(rule_name: str, retry_after: int) -> JSONResponse:
    from argus_py.api.errors import error_response

    return error_response(
        code="RATE_LIMITED",
        message="请求过于频繁，请稍后再试。",
        http_status=429,
        details={"rule": rule_name, "retryAfter": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


def build_rules(raw: list[dict[str, Any]]) -> list[RateLimitRule]:
    """把 server.yaml 中的 list[dict] 转成 ``RateLimitRule`` 列表。

    非法/不完整的条目被跳过并打 warning，整体不抛错，避免运维误配让整个进程
    起不来。
    """
    rules: list[RateLimitRule] = []
    for idx, item in enumerate(raw or []):
        if not isinstance(item, dict):
            logger.warning("rate_limit.routes[%d] 不是 dict，已忽略", idx)
            continue
        name = str(item.get("name") or "").strip()
        method = str(item.get("method") or "").strip().upper()
        path_pattern = str(item.get("path") or "").strip()
        rpm = _as_positive_float(item.get("requests_per_minute"))
        burst = _as_positive_float(item.get("burst"))
        if not (name and method and path_pattern and rpm > 0 and burst > 0):
            logger.warning(
                "rate_limit.routes[%d] 字段不完整，已忽略：name=%r method=%r path=%r rpm=%r burst=%r",
                idx,
                name,
                method,
                path_pattern,
                rpm,
                burst,
            )
            continue
        rules.append(
            RateLimitRule(
                name=name,
                method=method,
                path_pattern=path_pattern,
                capacity=burst,
                refill_per_sec=rpm / 60.0,
            )
        )
    return rules


def _as_positive_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result > 0 else 0.0
