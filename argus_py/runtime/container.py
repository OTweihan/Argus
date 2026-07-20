"""运行时容器：框架无关的组合根，直接构造子服务而非经过 deprecated facade。

各消费者（FastAPI、CLI、Worker 独立进程）通过此容器
获取已装配好的服务实例，而不是自行组装。"""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass
from functools import lru_cache

from argus_py.config.server_settings import ServerSettings, load_server_settings
from argus_py.config.service import ModelConfigService
from argus_py.infra.db import set_default_pool_max_size
from argus_py.infra.events import EventBus
from argus_py.infra.queue import TaskQueue
from argus_py.infra.worker import TaskWorker
from argus_py.llm.client import set_llm_semaphore
from argus_py.observability.audit import AuditService, set_audit_service
from argus_py.observability.debug_bundle import DebugBundleBuilder
from argus_py.observability.trace_reader import TraceReadService
from argus_py.project.service import ProjectService
from argus_py.task.event import TaskTimelineService, _NullTimelineService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.log import TaskLogService
from argus_py.task.read import TaskReadService
from argus_py.task.service import TaskService  # backward compat
from argus_py.task.storage import TaskSQLiteStorage


@dataclass(frozen=True)
class RuntimeContainer:
    """运行时容器：保存所有已初始化服务的引用。
    新代码优先使用具体子服务而非 ``task_service`` facade。"""

    settings: ServerSettings
    event_bus: EventBus
    audit_service: AuditService
    task_service: TaskService
    lifecycle_service: TaskLifecycleService
    log_service: TaskLogService
    task_read_service: TaskReadService
    trace_reader_service: TraceReadService
    debug_bundle_builder: DebugBundleBuilder
    timeline_service: TaskTimelineService | _NullTimelineService
    project_service: ProjectService
    model_config_service: ModelConfigService
    task_queue: TaskQueue
    task_worker: TaskWorker
    llm_semaphore: asyncio.Semaphore | None


@lru_cache
def create_container() -> RuntimeContainer:
    """创建（或返回已缓存的）运行时容器单例。

    注意：``@lru_cache`` 保证单例但可能会造成测试跨用例污染。测试中若直接调用此函数，
    务必在 teardown 中执行 ``create_container.cache_clear()`` 清除缓存。
    """
    settings = load_server_settings()

    set_default_pool_max_size(settings.db_pool_max_size)

    event_bus = EventBus(
        history_limit=settings.events_history_limit,
        subscriber_queue_size=settings.events_subscriber_queue_size,
        max_subscribers=settings.events_max_subscribers,
    )

    audit_service = AuditService(
        event_publisher=event_bus.publish if settings.observability_audit_logging else None,
    )
    set_audit_service(audit_service)

    model_config_service = ModelConfigService()
    task_queue = TaskQueue(max_size=settings.scheduler_queue_max_size)

    # ── 直接构造子服务，绕过 deprecated TaskService facade ──
    storage = TaskSQLiteStorage()
    lifecycle_service = TaskLifecycleService(storage, event_publisher=event_bus.publish)
    log_service = TaskLogService(storage, event_publisher=event_bus.publish)
    task_read_service = TaskReadService(storage)
    trace_reader_service = TraceReadService()
    debug_bundle_builder = DebugBundleBuilder()
    timeline_service = (
        TaskTimelineService(storage, event_publisher=event_bus.publish)
        if isinstance(storage, TaskSQLiteStorage)
        else _NullTimelineService()
    )

    # backward compat: 保持 task_service facade 可用
    # 新代码通过容器字段直接获取子服务
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="TaskService is deprecated", category=DeprecationWarning
        )
        task_service = TaskService(storage=storage, event_publisher=event_bus.publish)

    project_service = ProjectService(task_read_service=task_read_service)

    task_worker = TaskWorker(
        queue=task_queue,
        lifecycle=lifecycle_service,
        reader=task_read_service,
        concurrency=settings.scheduler_concurrency,
        model_config_service=model_config_service,
    )

    llm_semaphore = (
        asyncio.Semaphore(settings.llm_max_inflight) if settings.llm_max_inflight > 0 else None
    )
    if llm_semaphore is not None:
        set_llm_semaphore(llm_semaphore)

    return RuntimeContainer(
        settings=settings,
        event_bus=event_bus,
        audit_service=audit_service,
        task_service=task_service,
        lifecycle_service=lifecycle_service,
        log_service=log_service,
        task_read_service=task_read_service,
        trace_reader_service=trace_reader_service,
        debug_bundle_builder=debug_bundle_builder,
        timeline_service=timeline_service,
        project_service=project_service,
        model_config_service=model_config_service,
        task_queue=task_queue,
        task_worker=task_worker,
        llm_semaphore=llm_semaphore,
    )


async def shutdown_container() -> None:
    """优雅关闭容器持有的所有共享资源。

    包括：
    - Playwright 浏览器进程（若已启动）

    调用时机：Worker 停机、FastAPI lifespan shutdown、CLI 命令结束。
    安全可重入：未初始化的资源静默跳过。
    """
    from argus_py.browser.singleton import stop_shared_client

    await stop_shared_client()
