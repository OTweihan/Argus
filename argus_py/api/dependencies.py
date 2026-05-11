"""FastAPI 依赖注入 — 仅做框架适配，组合逻辑在 runtime.container。"""

from functools import lru_cache

from argus_py.config.server_settings import load_server_settings  # noqa: F401
from argus_py.config.service import ModelConfigService
from argus_py.infra.events import EventBus
from argus_py.infra.queue import TaskQueue
from argus_py.infra.worker import TaskWorker
from argus_py.observability.audit import AuditService
from argus_py.project.service import ProjectService
from argus_py.runtime.container import create_container
from argus_py.task.service import TaskService


@lru_cache
def get_event_bus() -> EventBus:
    return create_container().event_bus


@lru_cache
def get_audit_service() -> AuditService:
    return create_container().audit_service


@lru_cache
def get_task_service() -> TaskService:
    return create_container().task_service


@lru_cache
def get_project_service() -> ProjectService:
    return create_container().project_service


@lru_cache
def get_model_config_service() -> ModelConfigService:
    return create_container().model_config_service


@lru_cache
def get_task_queue() -> TaskQueue:
    return create_container().task_queue


@lru_cache
def get_task_worker() -> TaskWorker:
    return create_container().task_worker
