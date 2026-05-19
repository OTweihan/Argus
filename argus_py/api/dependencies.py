"""FastAPI 依赖注入 — 仅做框架适配，组合逻辑在 runtime.container。"""

from functools import lru_cache
from typing import TYPE_CHECKING

from argus_py.config.server_settings import load_server_settings  # noqa: F401
from argus_py.config.service import ModelConfigService
from argus_py.infra.events import EventBus
from argus_py.infra.queue import TaskQueue
from argus_py.infra.worker import TaskWorker
from argus_py.observability.audit import AuditService
from argus_py.project.service import ProjectService
from argus_py.runtime.container import create_container
from argus_py.task.event import TaskTimelineService, _NullTimelineService
from argus_py.task.query import TaskQueryService
from argus_py.task.service import TaskService

if TYPE_CHECKING:
    from argus_py.task.application import TaskApplicationService


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


@lru_cache
def get_task_app_service() -> "TaskApplicationService":
    from argus_py.task.application import TaskApplicationService

    c = create_container()
    return TaskApplicationService(
        task_service=c.task_service,
        queue=c.task_queue,
        project_service=c.project_service,
        model_config_service=c.model_config_service,
    )


@lru_cache
def get_task_query_service() -> TaskQueryService:
    """返回 TaskQueryService（从容器 TaskService 中提取）。"""
    return create_container().task_service.query


@lru_cache
def get_task_timeline_service() -> TaskTimelineService | _NullTimelineService:
    """返回 TaskTimelineService（从容器 TaskService 中提取）。"""
    return create_container().task_service.timeline


def reset_all_dependencies() -> None:
    """重置所有 lru_cache 单例，用于测试间隔离。

    测试 teardown 中调用本函数可确保下次 ``Depends(get_xxx)`` 拿到新实例，
    避免缓存污染跨用例传递。
    """
    get_event_bus.cache_clear()
    get_audit_service.cache_clear()
    get_task_service.cache_clear()
    get_project_service.cache_clear()
    get_model_config_service.cache_clear()
    get_task_queue.cache_clear()
    get_task_worker.cache_clear()
    get_task_app_service.cache_clear()
