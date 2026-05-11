"""FastAPI 依赖注入与服务配置。"""

from __future__ import annotations

from functools import lru_cache

from argus_py.config.server_settings import ServerSettings, load_server_settings
from argus_py.config.service import ModelConfigService
from argus_py.infra.events import EventBus
from argus_py.infra.queue import TaskQueue
from argus_py.infra.worker import TaskWorker
from argus_py.project.service import ProjectService
from argus_py.task.service import TaskService


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
