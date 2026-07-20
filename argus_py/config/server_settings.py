"""服务端配置加载与类型转换。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from argus_py.core.paths import resolve_project_path
from argus_py.utils.parse import parse_bool as _as_bool

DEFAULT_SERVER_CONFIG = "config/server.yaml"
SERVER_CONFIG_ENV = "ARGUS_SERVER_CONFIG"


@dataclass(frozen=True)
class ServerSettings:
    """Web 服务运行配置。"""

    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    cors_allow_origins: list[str] = field(default_factory=lambda: ["http://localhost:8000"])
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = field(default_factory=lambda: ["*"])
    cors_allow_headers: list[str] = field(default_factory=lambda: ["*"])
    scheduler_concurrency: int = 1
    scheduler_queue_max_size: int = 0
    scheduler_shutdown_timeout_seconds: float = 5.0
    db_pool_max_size: int = 8
    events_history_limit: int = 200
    events_subscriber_queue_size: int = 100
    # 全局 WebSocket / 事件订阅数硬上限。0 = 不限（向后兼容）。
    # 私网部署建议设为 200 左右，防止异常前端反复重连耗尽 asyncio.Queue 内存。
    events_max_subscribers: int = 0
    observability_request_logging: bool = True
    observability_operation_logging: bool = True
    observability_audit_logging: bool = True
    # 全局请求 body 大小上限（字节），0 表示不限制。默认 5MB 足以覆盖正常 task
    # 表单 / prompt 预览 / 模型配置等场景，又能拦住误粘超大 payload。
    request_max_body_size_bytes: int = 5 * 1024 * 1024
    llm_trace_enabled: bool = True
    llm_trace_max_size_mb: int = 50
    llm_trace_content_redact: bool = True
    # 集中后台写入（默认开启）+ 启动期 TTL / 总量清理。早期同步 append 是性能与
    # 磁盘膨胀的双重风险：长期跑下来 outputs/traces 会无限增长。这里把写入排队给
    # 独立线程，并在 startup 清理过旧 / 超量文件。
    llm_trace_async_writer: bool = True
    llm_trace_writer_queue_size: int = 10000
    llm_trace_writer_batch_size: int = 32
    llm_trace_writer_flush_interval: float = 0.5
    llm_trace_retention_days: int = 7
    llm_trace_total_size_mb: int = 500
    # SSRF 防御白名单：允许 LLM base_url 指向哪些内网/特殊主机
    # 默认 localhost / 127.0.0.1 由 url_guard 内置放行（同机 Ollama 场景）
    # 其余 RFC1918 私网、metadata 等默认拒绝
    llm_allow_private_hosts: list[str] = field(default_factory=list)
    # LLM 全局并发上限：asyncio.Semaphore 控制并行 planner+evaluator 总请求数，
    # 防止 scheduler.concurrency > 1 时瞬间打满外部 LLM 限流。0 = 不限。
    llm_max_inflight: int = 8
    # 限流：进程内 token bucket，默认禁用。
    # rate_limit_routes 每项 dict 形如：
    #   {name, method, path, requests_per_minute, burst}
    rate_limit_enabled: bool = False
    rate_limit_trust_forwarded: bool = False
    rate_limit_routes: list[dict[str, Any]] = field(default_factory=list)


def load_server_settings(path: str | Path = DEFAULT_SERVER_CONFIG) -> ServerSettings:
    """加载 Web 服务配置。"""
    config_path = os.getenv(SERVER_CONFIG_ENV, str(path))
    data = _read_server_config(config_path)
    server = data.get("server") or {}
    cors = data.get("cors") or {}
    scheduler = data.get("scheduler") or {}
    events = data.get("events") or {}
    observability = data.get("observability") or {}
    llm_trace = observability.get("llm_trace") or {}
    llm = data.get("llm") or {}
    rate_limit = data.get("rate_limit") or {}
    rate_limit_routes_raw = rate_limit.get("routes") or []
    rate_limit_routes = [item for item in rate_limit_routes_raw if isinstance(item, dict)]
    return ServerSettings(
        host=str(server.get("host", "127.0.0.1")),
        port=_as_int(server.get("port"), 8000, minimum=1),
        reload=_as_bool(server.get("reload"), False),
        db_pool_max_size=_as_int(data.get("db_pool_max_size"), 8, minimum=1),
        cors_allow_origins=_as_str_list(cors.get("allow_origins"), ["http://localhost:8000"]),
        cors_allow_credentials=_as_bool(cors.get("allow_credentials"), True),
        cors_allow_methods=_as_str_list(cors.get("allow_methods"), ["*"]),
        cors_allow_headers=_as_str_list(cors.get("allow_headers"), ["*"]),
        scheduler_concurrency=_as_int(scheduler.get("concurrency"), 1, minimum=1),
        scheduler_queue_max_size=_as_int(scheduler.get("queue_max_size"), 0, minimum=0),
        scheduler_shutdown_timeout_seconds=_as_float(
            scheduler.get("shutdown_timeout_seconds"),
            5.0,
            minimum=0,
        ),
        events_history_limit=_as_int(events.get("history_limit"), 200, minimum=0),
        events_subscriber_queue_size=_as_int(events.get("subscriber_queue_size"), 100, minimum=1),
        events_max_subscribers=_as_int(events.get("max_subscribers"), 0, minimum=0),
        observability_request_logging=_as_bool(
            observability.get("request_logging"),
            True,
        ),
        observability_operation_logging=_as_bool(
            observability.get("operation_logging"),
            True,
        ),
        observability_audit_logging=_as_bool(
            observability.get("audit_logging"),
            True,
        ),
        request_max_body_size_bytes=_as_int(
            (data.get("request") or {}).get("max_body_size_bytes"),
            5 * 1024 * 1024,
            minimum=0,
        ),
        llm_trace_enabled=_as_bool(llm_trace.get("enabled"), True),
        llm_trace_max_size_mb=_as_int(llm_trace.get("max_size_mb"), 50, minimum=0),
        llm_trace_content_redact=_as_bool(llm_trace.get("content_redact"), True),
        llm_trace_async_writer=_as_bool(llm_trace.get("async_writer"), True),
        llm_trace_writer_queue_size=_as_int(llm_trace.get("writer_queue_size"), 10000, minimum=64),
        llm_trace_writer_batch_size=_as_int(llm_trace.get("writer_batch_size"), 32, minimum=1),
        llm_trace_writer_flush_interval=_as_float(
            llm_trace.get("writer_flush_interval"), 0.5, minimum=0.05
        ),
        llm_trace_retention_days=_as_int(llm_trace.get("retention_days"), 7, minimum=0),
        llm_trace_total_size_mb=_as_int(llm_trace.get("total_size_mb"), 500, minimum=0),
        llm_allow_private_hosts=_as_str_list(llm.get("allow_private_hosts"), []),
        llm_max_inflight=_as_int(llm.get("max_inflight"), 8, minimum=0),
        rate_limit_enabled=_as_bool(rate_limit.get("enabled"), False),
        rate_limit_trust_forwarded=_as_bool(rate_limit.get("trust_forwarded"), False),
        rate_limit_routes=rate_limit_routes,
    )


def _read_server_config(path: str | Path) -> dict[str, Any]:
    """读取 server.yaml，文件缺失时使用默认配置。"""
    config_path = resolve_project_path(path)
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _as_int(value: Any, default: int, minimum: int | None = None) -> int:
    """把配置值转换为 int，非法值回退默认值。"""
    try:
        resolved = int(value if value is not None else default)
    except (TypeError, ValueError):
        resolved = default
    return max(minimum, resolved) if minimum is not None else resolved


def _as_float(value: Any, default: float, minimum: float | None = None) -> float:
    """把配置值转换为 float，非法值回退默认值。"""
    try:
        resolved = float(value if value is not None else default)
    except (TypeError, ValueError):
        resolved = default
    return max(minimum, resolved) if minimum is not None else resolved


def _as_str_list(value: Any, default: list[str]) -> list[str]:
    """把配置中的字符串或列表统一转换为字符串列表。"""
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()] or list(default)
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return list(default)
