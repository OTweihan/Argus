"""FastAPI 依赖注入与服务配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from argus_py.config.service import ModelConfigService
from argus_py.core.paths import resolve_project_path
from argus_py.infra.events import EventBus
from argus_py.infra.queue import TaskQueue
from argus_py.infra.worker import TaskWorker
from argus_py.project.service import ProjectService
from argus_py.task.service import TaskService

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
    events_history_limit: int = 200
    events_subscriber_queue_size: int = 100


def _read_server_config(path: str | Path) -> dict[str, Any]:
    """读取 server.yaml，文件缺失时使用默认配置。"""
    config_path = resolve_project_path(path)
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


@lru_cache
def load_server_settings(path: str | Path = DEFAULT_SERVER_CONFIG) -> ServerSettings:
    """加载 Web 服务配置。"""
    config_path = os.getenv(SERVER_CONFIG_ENV, str(path))
    data = _read_server_config(config_path)
    server = data.get("server") or {}
    cors = data.get("cors") or {}
    scheduler = data.get("scheduler") or {}
    events = data.get("events") or {}
    return ServerSettings(
        host=str(server.get("host", "127.0.0.1")),
        port=_as_int(server.get("port"), 8000, minimum=1),
        reload=_as_bool(server.get("reload"), False),
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
    )


def _as_bool(value: Any, default: bool) -> bool:
    """把 YAML 中常见布尔写法统一转换为 bool。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
        return default
    return bool(value)


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


@lru_cache
def get_event_bus() -> EventBus:
    """返回事件总线单例。"""
    settings = load_server_settings()
    return EventBus(
        history_limit=settings.events_history_limit,
        subscriber_queue_size=settings.events_subscriber_queue_size,
    )


@lru_cache
def get_task_service() -> TaskService:
    """返回任务服务单例。"""
    return TaskService(event_publisher=get_event_bus().publish)


@lru_cache
def get_project_service() -> ProjectService:
    """返回项目服务单例。"""
    return ProjectService(task_service=get_task_service())


@lru_cache
def get_model_config_service() -> ModelConfigService:
    """返回模型配置服务单例。"""
    return ModelConfigService()


@lru_cache
def get_task_queue() -> TaskQueue:
    """返回任务队列单例。"""
    settings = load_server_settings()
    return TaskQueue(max_size=settings.scheduler_queue_max_size)


@lru_cache
def get_task_worker() -> TaskWorker:
    """返回任务 Worker 单例。"""
    settings = load_server_settings()
    return TaskWorker(
        queue=get_task_queue(),
        service=get_task_service(),
        concurrency=settings.scheduler_concurrency,
    )
