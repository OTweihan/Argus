"""运行时容器：框架无关的组合根，直接构造子服务。

各消费者（FastAPI、CLI、Worker 独立进程）通过此容器
获取已装配好的服务实例，而不是自行组装。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from argus_py.config.server_settings import ServerSettings, load_server_settings
from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskType
from argus_py.core.ids import generate_id
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
from argus_py.task.storage import TaskSQLiteStorage
from argus_py.whitebox.client import WhiteboxClient
from argus_py.whitebox.runner import WhiteboxRunner
from argus_py.whitebox.source_resolver import SourceResolver

if TYPE_CHECKING:
    from argus_py.task.application import TaskApplicationService

_TASK_HANDLER_TYPE = dict


@dataclass(frozen=True)
class RuntimeContainer:
    """运行时容器：保存所有已初始化服务的引用。"""

    settings: ServerSettings
    event_bus: EventBus
    audit_service: AuditService
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
    # 白盒
    whitebox_client: WhiteboxClient
    whitebox_runner: WhiteboxRunner
    # 业务 handler 注册表（供测试/自定义注入）
    task_handlers: _TASK_HANDLER_TYPE


def create_task_application_service(
    container: RuntimeContainer,
) -> TaskApplicationService:
    """创建 TaskApplicationService，聚合容器中的子服务。"""
    from argus_py.task.application import TaskApplicationService

    return TaskApplicationService(
        lifecycle=container.lifecycle_service,
        task_read=container.task_read_service,
        queue=container.task_queue,
        project_service=container.project_service,
        model_config_service=container.model_config_service,
    )


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

    # ── 直接构造子服务 ──
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

    project_service = ProjectService(task_read_service=task_read_service)

    # ── 白盒：SourceResolver ──
    source_resolver = SourceResolver(
        work_dir=settings.whitebox_source_work_dir,
        allowed_roots=[Path(p) for p in settings.whitebox_allowed_source_roots],
    )

    # ── 白盒：WhiteboxClient ──
    whitebox_client = WhiteboxClient(
        base_url=settings.java_analyzer_url,
        request_timeout=settings.java_analyzer_request_timeout,
    )

    # ── 白盒：WhiteboxRunner ──
    whitebox_runner = WhiteboxRunner(
        client=whitebox_client,
        source_resolver=source_resolver,
        timeline_service=timeline_service,
        lifecycle=lifecycle_service,
    )

    # ── 黑盒：BlackboxRunner ──
    from argus_py.blackbox.runner import BlackboxRunner

    blackbox_runner = BlackboxRunner(
        lifecycle=lifecycle_service,
        reader=task_read_service,
        log_service=log_service,
        timeline_service=timeline_service,
        model_config_service=model_config_service,
    )

    # ── Handler 装配 ──
    handlers: _TASK_HANDLER_TYPE = {
        TaskType.BLACKBOX: blackbox_runner.run,
        TaskType.WHITEBOX: whitebox_runner.run,
    }

    # 生成 Worker 标识（单进程单 Worker，ID 稳定）
    worker_id = getattr(settings, "worker_id", "") or generate_id("w")

    task_worker = TaskWorker(
        queue=task_queue,
        lifecycle=lifecycle_service,
        reader=task_read_service,
        handlers=handlers,
        concurrency=settings.scheduler_concurrency,
        model_config_service=model_config_service,
        worker_id=worker_id,
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
        whitebox_client=whitebox_client,
        whitebox_runner=whitebox_runner,
        task_handlers=handlers,
    )


async def shutdown_container() -> None:
    """优雅关闭容器持有的所有共享资源。

    包括：
    - WhiteboxClient HTTP 连接
    - Playwright 浏览器进程（若已启动）
    - 数据库连接池

    调用时机：Worker 停机、FastAPI lifespan shutdown、CLI 命令结束。
    安全可重入：未初始化的资源静默跳过。
    """
    from argus_py.browser.singleton import stop_shared_client
    from argus_py.infra.db import close_all_db_pools

    container = create_container()
    try:
        await container.whitebox_client.aclose()
    except Exception:
        pass
    await stop_shared_client()
    close_all_db_pools()
    create_container.cache_clear()
