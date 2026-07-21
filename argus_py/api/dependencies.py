"""FastAPI 依赖注入 — 仅做框架适配，组合逻辑在 runtime.container。"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

from argus_py.config.service import ModelConfigService
from argus_py.core.exceptions import TaskNotFoundError
from argus_py.infra.events import EventBus
from argus_py.infra.queue import TaskQueue
from argus_py.infra.worker import TaskWorker
from argus_py.observability.audit import AuditService
from argus_py.observability.context import run_in_thread
from argus_py.observability.debug_bundle import DebugBundleBuilder
from argus_py.observability.trace_reader import TraceReadService
from argus_py.project.service import ProjectService
from argus_py.runtime.container import create_container, create_task_application_service
from argus_py.task.event import TaskTimelineService, _NullTimelineService
from argus_py.task.read import TaskReadService

if TYPE_CHECKING:
    from argus_py.task.application import TaskApplicationService


@lru_cache
def get_event_bus() -> EventBus:
    return create_container().event_bus


@lru_cache
def get_audit_service() -> AuditService:
    return create_container().audit_service


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
    return create_task_application_service(create_container())


@lru_cache
def get_task_timeline_service() -> TaskTimelineService | _NullTimelineService:
    """返回 TaskTimelineService（从容器直接提取）。"""
    return create_container().timeline_service


@lru_cache
def get_task_read_service() -> TaskReadService:
    """返回 TaskReadService（从容器直接提取）。"""
    return create_container().task_read_service


@lru_cache
def get_trace_reader_service() -> TraceReadService:
    """返回 TraceReadService（从容器直接提取）。"""
    return create_container().trace_reader_service


@lru_cache
def get_debug_bundle_builder() -> DebugBundleBuilder:
    """返回 DebugBundleBuilder（从容器直接提取）。"""
    return create_container().debug_bundle_builder


async def require_task_exists(
    task_id: str,
    reader: TaskReadService = Depends(get_task_read_service),
) -> None:
    """校验任务存在，不存在时 ``TaskNotFoundError`` 由全局 handler 转 404。"""
    if not await run_in_thread(reader.task_exists, task_id):
        raise TaskNotFoundError(f"任务不存在：{task_id}")


TaskExistsDep = Annotated[None, Depends(require_task_exists)]
"""注入后自动校验任务是否存在。"""


def reset_all_dependencies() -> None:
    """重置所有 lru_cache 单例，用于测试间隔离。

    测试 teardown 中调用本函数可确保下次 ``Depends(get_xxx)`` 拿到新实例，
    避免缓存污染跨用例传递。
    """
    get_event_bus.cache_clear()
    get_audit_service.cache_clear()
    get_project_service.cache_clear()
    get_model_config_service.cache_clear()
    get_task_queue.cache_clear()
    get_task_worker.cache_clear()
    get_task_timeline_service.cache_clear()
    get_task_read_service.cache_clear()
    get_trace_reader_service.cache_clear()
    get_debug_bundle_builder.cache_clear()
    get_task_app_service.cache_clear()
    # 运行时容器与 LLM 信号量同样需要在测试间重置，防止 asyncio.Semaphore
    # 跨 event loop 复用导致 ``RuntimeError``。
    from argus_py.runtime.container import create_container

    create_container.cache_clear()
    from argus_py.llm.client import set_llm_semaphore

    set_llm_semaphore(None)
