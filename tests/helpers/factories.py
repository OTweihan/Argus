"""测试工厂：统一构建服务栈，避免各测试文件重复搭建 storage / service / queue。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from argus_py.config.model_storage import ModelConfigSQLiteStorage
from argus_py.config.service import ModelConfigService
from argus_py.infra.queue import TaskQueue
from argus_py.project.service import ProjectService
from argus_py.project.storage import ProjectSQLiteStorage
from argus_py.task.application import TaskApplicationService
from argus_py.task.service import TaskService
from argus_py.task.storage import TaskFileStorage


@dataclass
class AppStack:
    app: TaskApplicationService
    task_service: TaskService
    project_service: ProjectService
    queue: TaskQueue


def make_app_stack(
    tmp_path: Path,
    *,
    event_publisher: Callable | None = None,
) -> AppStack:
    """构建完整的服务栈，供单测和 e2e 测试复用。

    Args:
        tmp_path: pytest 提供的临时目录，各测试隔离。
        event_publisher: 可选的事件发布回调，e2e 测试传入 EventBus.publish。
    """
    task_service = TaskService(
        TaskFileStorage(tmp_path / "tasks"),
        event_publisher=event_publisher,
    )
    project_service = ProjectService(
        ProjectSQLiteStorage(tmp_path / "argus.db"),
        task_service=task_service,
    )
    queue = TaskQueue()
    app = TaskApplicationService(
        task_service=task_service,
        queue=queue,
        project_service=project_service,
        model_config_service=ModelConfigService(ModelConfigSQLiteStorage(tmp_path / "models.db")),
    )
    return AppStack(
        app=app, task_service=task_service, project_service=project_service, queue=queue
    )
