"""运行时容器：框架无关的组合根。

负责按正确顺序创建和组装所有运行时对象。各消费者（FastAPI、CLI、Worker 独立进程）
通过此容器获取已装配好的服务实例，而不是自行组装。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from argus_py.config.server_settings import ServerSettings, load_server_settings
from argus_py.config.service import ModelConfigService
from argus_py.infra.events import EventBus
from argus_py.infra.queue import TaskQueue
from argus_py.infra.worker import TaskWorker
from argus_py.observability.audit import AuditService, set_audit_service
from argus_py.project.service import ProjectService
from argus_py.task.service import TaskService


@dataclass(frozen=True)
class RuntimeContainer:
    """运行时容器：保存所有已初始化服务的引用。"""

    settings: ServerSettings
    event_bus: EventBus
    audit_service: AuditService
    task_service: TaskService
    project_service: ProjectService
    model_config_service: ModelConfigService
    task_queue: TaskQueue
    task_worker: TaskWorker


@lru_cache
def create_container() -> RuntimeContainer:
    """创建（或返回已缓存的）运行时容器单例。

    注意：``@lru_cache`` 保证单例但可能会造成测试跨用例污染。测试中若直接调用此函数，
    务必在 teardown 中执行 ``create_container.cache_clear()`` 清除缓存。
    """
    settings = load_server_settings()

    event_bus = EventBus(
        history_limit=settings.events_history_limit,
        subscriber_queue_size=settings.events_subscriber_queue_size,
    )

    audit_service = AuditService(
        event_publisher=event_bus.publish if settings.observability_audit_logging else None,
    )

    set_audit_service(audit_service)

    task_service = TaskService(event_publisher=event_bus.publish)

    project_service = ProjectService(task_service=task_service)

    model_config_service = ModelConfigService()

    task_queue = TaskQueue(max_size=settings.scheduler_queue_max_size)

    task_worker = TaskWorker(
        queue=task_queue,
        service=task_service,
        concurrency=settings.scheduler_concurrency,
    )

    return RuntimeContainer(
        settings=settings,
        event_bus=event_bus,
        audit_service=audit_service,
        task_service=task_service,
        project_service=project_service,
        model_config_service=model_config_service,
        task_queue=task_queue,
        task_worker=task_worker,
    )
