"""测试工厂：统一构建服务栈，使用 SQLite 存储对齐生产环境。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from argus_py.config.model_storage import ModelConfigSQLiteStorage
from argus_py.config.service import ModelConfigService
from argus_py.infra.queue import TaskQueue
from argus_py.observability.debug_bundle import DebugBundleBuilder
from argus_py.observability.trace_reader import TraceReadService
from argus_py.project.service import ProjectService
from argus_py.project.storage import ProjectSQLiteStorage
from argus_py.task.application import TaskApplicationService
from argus_py.task.event import TaskTimelineService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.log import TaskLogService
from argus_py.task.read import TaskReadService
from argus_py.task.storage import TaskSQLiteStorage


@dataclass
class AppStack:
    """测试服务栈，所有服务使用 SQLite 存储对齐生产环境。"""
    app: TaskApplicationService
    lifecycle: TaskLifecycleService
    reader: TaskReadService
    log: TaskLogService
    trace_reader: TraceReadService
    debug_builder: DebugBundleBuilder
    timeline: TaskTimelineService
    project_service: ProjectService
    queue: TaskQueue


def make_app_stack(
    tmp_path: Path,
    *,
    event_publisher: Callable | None = None,
) -> AppStack:
    """构建完整的服务栈，供单测和 e2e 测试复用。

    Args:
        tmp_path: pytest 提供的临时目录，各测试隔离（SQLite 数据库建在此目录下）。
        event_publisher: 可选的事件发布回调，e2e 测试传入 EventBus.publish。
    """
    storage = TaskSQLiteStorage(tmp_path / "argus.db")
    lifecycle = TaskLifecycleService(storage, event_publisher=event_publisher)
    reader = TaskReadService(storage)
    log = TaskLogService(storage, event_publisher=event_publisher)
    trace_reader = TraceReadService()
    debug_builder = DebugBundleBuilder()
    timeline = TaskTimelineService(storage, event_publisher=event_publisher)
    project_service = ProjectService(
        ProjectSQLiteStorage(tmp_path / "argus.db"),
        task_read_service=reader,
    )
    queue = TaskQueue()
    app = TaskApplicationService(
        lifecycle=lifecycle,
        task_read=reader,
        queue=queue,
        project_service=project_service,
        model_config_service=ModelConfigService(ModelConfigSQLiteStorage(tmp_path / "models.db")),
    )
    return AppStack(
        app=app,
        lifecycle=lifecycle,
        reader=reader,
        log=log,
        trace_reader=trace_reader,
        debug_builder=debug_builder,
        timeline=timeline,
        project_service=project_service,
        queue=queue,
    )
