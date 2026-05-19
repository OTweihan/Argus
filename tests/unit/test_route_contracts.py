"""路由层契约单测：聚焦 application 层错误 → ``HTTPException`` 的转换。

不启动 ASGI 服务器，直接以异步函数调用方式驱动路由处理器，验证：

- HTTP status code
- ``HTTPException.detail`` 中携带的 ``code``、``message``、``details``
- 正常路径下返回 schema 字段

这样既覆盖了 ``TaskAppError → HTTPException`` 的桥接，又不引入 TestClient 的额外依赖。

业务路径 (start/cancel/pause/resume/delete/restart/update) 在 ``application.py`` 已经有大量
状态机校验，本文件确保每条路径的错误码以及最终路由响应都被冻结成契约。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.integration

from argus_py.api.routes import projects as project_routes
from argus_py.api.routes import tasks as task_routes
from argus_py.api.schemas import (
    ProjectCreateRequest,
    TaskCreateRequest,
    TaskUpdateRequest,
)
from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import ProjectError, TaskError
from tests.helpers.factories import make_app_stack

# ── Helpers ─────────────────────────────────────────────────────────────────


def _detail(exc: HTTPException) -> dict[str, Any]:
    """FastAPI HTTPException.detail 在这些路由里固定为错误响应 dict。"""
    return cast(dict[str, Any], exc.detail)


async def _create_project(project_service, **overrides) -> str:
    project = await project_routes.create_project(
        ProjectCreateRequest(
            name=overrides.pop("name", "契约测试项目"),
            base_url=overrides.pop("base_url", "https://example.com"),
            **overrides,
        ),
        service=project_service,
    )
    return project.project_id


async def _create_pending_task(app, project_id: str, *, goal: str = "契约任务"):
    return await task_routes.create_task(
        TaskCreateRequest(project_id=project_id, goal=goal, capture_screenshots=False),
        app=app,
    )


# ── 基础 happy path ─────────────────────────────────────────────────────────


async def test_create_task_happy_path_returns_pending(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    project_id = await _create_project(stack.project_service)

    response = await task_routes.create_task(
        TaskCreateRequest(project_id=project_id, goal="打开首页", capture_screenshots=False),
        app=stack.app,
    )

    assert response.status is TaskStatus.PENDING
    assert response.start_url == "https://example.com"
    assert response.capture_screenshots is False


async def test_get_task_404_when_missing(tmp_path: Path) -> None:
    """``TaskService.get_task`` 抛 ``TaskError`` → 由 middleware 翻译成 404；

    路由层本身不 catch ``TaskError``，会原样冒泡。本测试验证抛出类型/消息符合 contract。
    """
    stack = make_app_stack(tmp_path)

    with pytest.raises(TaskError, match="not found"):
        await task_routes.get_task("no-such", app=stack.app)


async def test_list_tasks_pagination_and_filter(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    project_id = await _create_project(stack.project_service)
    for i in range(3):
        await _create_pending_task(stack.app, project_id, goal=f"任务 {i}")

    # 直接 await 调路由函数会绕过 FastAPI 依赖解析，所有 Query/Path 形参的默认值
    # 都是 ``Query(...)`` 对象（非 int / str / None）。这里所有调用点必须显式
    # 传齐 status / project_id / q / offset / limit 五个参数，模拟 FastAPI 在
    # 真实请求中替我们填好的值。
    full = await task_routes.list_tasks(
        status=None, project_id=None, q=None, offset=0, limit=50, app=stack.app
    )
    assert full.total == 3
    assert len(full.tasks) == 3

    # offset/limit 分页
    page = await task_routes.list_tasks(
        status=None, project_id=None, q=None, offset=1, limit=1, app=stack.app
    )
    assert page.total == 3
    assert len(page.tasks) == 1

    # status=PENDING 过滤
    pending = await task_routes.list_tasks(
        status=TaskStatus.PENDING, project_id=None, q=None, offset=0, limit=50, app=stack.app
    )
    assert pending.total == 3

    # status=COMPLETED 应该过滤为空
    completed_list = await task_routes.list_tasks(
        status=TaskStatus.COMPLETED, project_id=None, q=None, offset=0, limit=50, app=stack.app
    )
    assert completed_list.total == 0


async def test_infer_limits_returns_positive_numbers(tmp_path: Path) -> None:
    response = await task_routes.infer_limits(
        goal="打开首页并截图", start_url="https://example.com"
    )
    assert response.max_steps > 0
    assert response.timeout_seconds > 0


# ── application 层错误码契约 ────────────────────────────────────────────────


async def test_start_task_409_when_already_running(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    project_id = await _create_project(stack.project_service)
    pending = await _create_pending_task(stack.app, project_id)
    # 直接把任务推进到 RUNNING（绕过队列），模拟 worker 已经接管
    stack.task_service.start_task(stack.task_service.get_task(pending.task_id))

    with pytest.raises(HTTPException) as exc_info:
        await task_routes.start_task(pending.task_id, app=stack.app)

    assert exc_info.value.status_code == 409
    assert _detail(exc_info.value)["code"] == "TASK_NOT_PENDING"
    assert _detail(exc_info.value)["details"]["status"] == "running"


async def test_pause_task_409_when_not_running(tmp_path: Path) -> None:
    """pending 状态不允许暂停。"""
    stack = make_app_stack(tmp_path)
    project_id = await _create_project(stack.project_service)
    pending = await _create_pending_task(stack.app, project_id)

    with pytest.raises(HTTPException) as exc_info:
        await task_routes.pause_task(pending.task_id, app=stack.app)

    assert exc_info.value.status_code == 409
    assert _detail(exc_info.value)["code"] == "TASK_NOT_RUNNING"


async def test_resume_task_409_when_not_paused(tmp_path: Path) -> None:
    """pending 状态不允许 resume。"""
    stack = make_app_stack(tmp_path)
    project_id = await _create_project(stack.project_service)
    pending = await _create_pending_task(stack.app, project_id)

    with pytest.raises(HTTPException) as exc_info:
        await task_routes.resume_task(pending.task_id, app=stack.app)

    assert exc_info.value.status_code == 409
    assert _detail(exc_info.value)["code"] == "TASK_NOT_PAUSED"


async def test_cancel_task_400_when_already_finished(tmp_path: Path) -> None:
    """终态任务取消应返回 400 + ``TASK_ALREADY_FINISHED``。"""
    stack = make_app_stack(tmp_path)
    project_id = await _create_project(stack.project_service)
    pending = await _create_pending_task(stack.app, project_id)
    # 直接把任务设为 COMPLETED
    running = stack.task_service.start_task(stack.task_service.get_task(pending.task_id))
    stack.task_service.complete_task(running, result_summary="人工标记完成")

    with pytest.raises(HTTPException) as exc_info:
        await task_routes.cancel_task(pending.task_id, app=stack.app)

    assert exc_info.value.status_code == 400
    assert _detail(exc_info.value)["code"] == "TASK_ALREADY_FINISHED"


async def test_restart_task_409_when_not_in_terminal_state(tmp_path: Path) -> None:
    """pending 状态不允许 restart（必须 failed/timeout/cancelled）。"""
    stack = make_app_stack(tmp_path)
    project_id = await _create_project(stack.project_service)
    pending = await _create_pending_task(stack.app, project_id)

    with pytest.raises(HTTPException) as exc_info:
        await task_routes.restart_task(pending.task_id, app=stack.app)

    assert exc_info.value.status_code == 409
    assert _detail(exc_info.value)["code"] == "TASK_NOT_RETRYABLE"


async def test_update_task_409_when_not_pending(tmp_path: Path) -> None:
    """RUNNING 任务不允许更新。"""
    stack = make_app_stack(tmp_path)
    project_id = await _create_project(stack.project_service)
    pending = await _create_pending_task(stack.app, project_id)
    stack.task_service.start_task(stack.task_service.get_task(pending.task_id))

    with pytest.raises(HTTPException) as exc_info:
        await task_routes.update_task(
            task_id=pending.task_id,
            request=TaskUpdateRequest(goal="改一下", project_id=project_id),
            app=stack.app,
        )

    assert exc_info.value.status_code == 409
    assert _detail(exc_info.value)["code"] == "TASK_NOT_EDITABLE"


async def test_delete_task_204_for_pending_and_409_for_running(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    project_id = await _create_project(stack.project_service)

    deletable = await _create_pending_task(stack.app, project_id, goal="可删任务")
    response = await task_routes.delete_task(deletable.task_id, app=stack.app)
    assert response.status_code == 204

    blocked = await _create_pending_task(stack.app, project_id, goal="阻塞删除任务")
    stack.task_service.start_task(stack.task_service.get_task(blocked.task_id))

    with pytest.raises(HTTPException) as exc_info:
        await task_routes.delete_task(blocked.task_id, app=stack.app)
    assert exc_info.value.status_code == 409
    assert _detail(exc_info.value)["code"] == "TASK_NOT_DELETABLE"


# ── 项目契约 ─────────────────────────────────────────────────────────────────


async def test_delete_project_with_attached_tasks_raises_project_error(tmp_path: Path) -> None:
    """有关联任务的项目删除应抛 ``ProjectError``（middleware 会翻成 400）。"""
    stack = make_app_stack(tmp_path)
    project_id = await _create_project(stack.project_service, name="待删除项目")
    await _create_pending_task(stack.app, project_id)

    with pytest.raises(ProjectError, match="不能删除"):
        await project_routes.delete_project(project_id, service=stack.project_service)


async def test_get_project_raises_project_not_found(tmp_path: Path) -> None:
    """``ProjectService.get_project`` 不存在 → ``ProjectError``。"""
    stack = make_app_stack(tmp_path)
    with pytest.raises(ProjectError, match="not found"):
        await project_routes.get_project("no-such-project", service=stack.project_service)
