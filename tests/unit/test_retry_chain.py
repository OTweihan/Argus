"""重试链命名与线性约束测试。

覆盖：
- 名称归一化（None / 空串 / 纯空白 / 首尾空格 / ID 兜底）
- Task 反序列化对 name、execution_attempt、retry_parent_task_id 的兼容
- 重试链：name 继承、attempt 递增、直接前驱指向、双向往返不丢链
- 线性约束：应用层拒绝重复重试、数据库唯一索引兜底
- 编辑三态：未提供 / 显式清空 / 正常值
- 删除子任务后父任务重新可重试（规则 B）
- API 响应暴露 executionAttempt（含列表摘要路径）
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from argus_py.api.routes import tasks as task_routes
from argus_py.api.schemas import (
    TaskCreateRequest,
    TaskResponse,
    TaskSummaryResponse,
    TaskUpdateRequest,
)
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskRetryConflictError
from argus_py.task.application import TaskAppError
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.models import Task, normalize_task_name
from argus_py.task.storage import TaskFileStorage, TaskSQLiteStorage
from argus_py.utils.jsonx import to_jsonable
from fastapi import HTTPException

from tests.helpers.factories import make_app_stack

pytestmark = pytest.mark.integration


# ── 名称归一化 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(None, "", id="none"),
        pytest.param("", "", id="empty"),
        pytest.param("   ", "", id="blank"),
        pytest.param("  名称  ", "名称", id="trim"),
    ],
)
def test_normalize_task_name_strips_and_falls_back(raw, expected):
    assert normalize_task_name(raw, "task-20260101-abcd1234") == (expected or "abcd1234")


def test_normalize_task_name_task_id_shorter_than_8():
    assert normalize_task_name(None, "task-xyz") == "task-xyz"


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_task_post_init_fills_name_from_task_id(raw):
    task = Task(goal="目标", name=raw)
    assert task.name == task.task_id[-8:]


def test_task_post_init_keeps_explicit_name():
    task = Task(goal="目标", name="  任务名  ")
    assert task.name == "任务名"


def test_task_from_dict_missing_name_falls_back():
    task = Task.from_dict({"goal": "目标", "task_id": "task-20260101-abcdef01"})
    assert task.name == "abcdef01"


def test_task_from_dict_missing_execution_attempt_defaults_to_1():
    task = Task.from_dict({"goal": "目标"})
    assert task.execution_attempt == 1


def test_task_to_jsonable_roundtrip_preserves_retry_parent(tmp_path: Path):
    parent = Task(goal="目标", name="任务名")
    child = Task(
        goal=parent.goal,
        name=parent.name,
        execution_attempt=parent.execution_attempt + 1,
        retry_parent_task_id=parent.task_id,
    )
    restored = Task.from_dict(to_jsonable(child))
    assert restored.retry_parent_task_id == parent.task_id
    assert restored.execution_attempt == 2


# ── 重试链行为（lifecycle） ───────────────────────────────────────────────────


@pytest.fixture
def chain_lifecycle(tmp_path: Path) -> TaskLifecycleService:
    return TaskLifecycleService(TaskSQLiteStorage(tmp_path / "argus.db"), event_publisher=None)


def _fail_task(lifecycle: TaskLifecycleService, task: Task) -> Task:
    lifecycle.update_status(task, TaskStatus.RUNNING)
    return lifecycle.update_status(task, TaskStatus.FAILED, "error")


def test_restart_inherits_name_and_builds_linear_chain(chain_lifecycle):
    lifecycle = chain_lifecycle
    a = lifecycle.create_task(goal="目标", name="漏洞扫描")
    a = _fail_task(lifecycle, a)

    b = lifecycle.restart_task(a)
    assert b.name == "漏洞扫描"  # 不再追加「-重试」后缀
    assert b.execution_attempt == 2
    assert b.retry_parent_task_id == a.task_id

    b = _fail_task(lifecycle, b)
    c = lifecycle.restart_task(b)
    assert c.name == "漏洞扫描"
    assert c.execution_attempt == 3
    assert c.retry_parent_task_id == b.task_id  # 直接前驱是 B，不是根 A
    assert c.retry_parent_task_id != a.task_id


def test_restart_without_name_uses_normalized_name(chain_lifecycle):
    lifecycle = chain_lifecycle
    a = lifecycle.create_task(goal="目标")
    a = _fail_task(lifecycle, a)
    assert a.name == a.task_id[-8:]

    b = lifecycle.restart_task(a)
    assert b.name == a.name
    assert b.retry_parent_task_id == a.task_id


def test_has_retry_child(chain_lifecycle):
    lifecycle = chain_lifecycle
    a = lifecycle.create_task(goal="目标", name="任务")
    assert lifecycle.has_retry_child(a.task_id) is False
    a = _fail_task(lifecycle, a)
    lifecycle.restart_task(a)
    assert lifecycle.has_retry_child(a.task_id) is True


def test_file_storage_roundtrip_preserves_retry_parent(tmp_path: Path):
    storage = TaskFileStorage(tmp_path / "tasks")
    parent = Task(goal="目标", name="任务名")
    storage.save(parent)
    child = Task(
        goal=parent.goal,
        name=parent.name,
        execution_attempt=2,
        retry_parent_task_id=parent.task_id,
    )
    storage.save(child)

    reloaded = TaskFileStorage(tmp_path / "tasks")  # 重建 storage 模拟重启
    restored = reloaded.load(child.task_id)
    assert restored.retry_parent_task_id == parent.task_id
    assert restored.execution_attempt == 2


# ── 应用层：线性约束 + 锁内二次校验 ───────────────────────────────────────────


def _create_project(stack) -> str:
    return stack.project_service.create_project(
        name="项目", base_url="https://example.com"
    ).project_id


def _make_failed_retryable(stack, project_id: str) -> str:
    """建一个 FAILED 可重试任务，返回 task_id。"""
    req = TaskCreateRequest(project_id=project_id, goal="重试链任务", capture_screenshots=False)
    params = stack.app.resolve_create_params(
        goal=req.goal,
        name=req.name,
        start_url=req.start_url,
        task_type=req.task_type,
        project_id=req.project_id,
        max_steps=req.max_steps,
        timeout_seconds=req.timeout_seconds,
        capture_screenshots=req.capture_screenshots,
        model_config_id=req.model_config_id,
        parameters=req.parameters,
        whitebox_config=req.whitebox_config,
    )
    task = stack.app.create_task(**params)
    task_id = task.task_id
    stack.app._lifecycle.update_status(task, TaskStatus.RUNNING)
    stack.app._lifecycle.update_status(task, TaskStatus.FAILED, "error")
    return task_id


async def test_app_restart_twice_rejects_second(tmp_path: Path):
    stack = make_app_stack(tmp_path)
    project_id = _create_project(stack)
    task_id = _make_failed_retryable(stack, project_id)

    await stack.app.restart_task(task_id)
    with pytest.raises(TaskAppError) as exc_info:
        await stack.app.restart_task(task_id)
    assert exc_info.value.code == "TASK_ALREADY_RETRIED"


async def test_restart_lock_cleaned_after_success(tmp_path: Path):
    """restart_task 成功后锁从字典清理，避免随重试次数无限增长。"""
    stack = make_app_stack(tmp_path)
    project_id = _create_project(stack)
    task_id = _make_failed_retryable(stack, project_id)

    assert task_id not in stack.app._restart_locks
    await stack.app.restart_task(task_id)
    assert task_id not in stack.app._restart_locks


async def test_restart_lock_cleaned_on_rejection(tmp_path: Path):
    """restart_task 被拒绝（已有子任务）时锁同样被清理。"""
    stack = make_app_stack(tmp_path)
    project_id = _create_project(stack)
    task_id = _make_failed_retryable(stack, project_id)

    await stack.app.restart_task(task_id)
    assert task_id not in stack.app._restart_locks
    with pytest.raises(TaskAppError) as exc_info:
        await stack.app.restart_task(task_id)
    assert exc_info.value.code == "TASK_ALREADY_RETRIED"
    assert task_id not in stack.app._restart_locks


async def test_app_restart_conflict_translated_to_409_route(tmp_path: Path):
    stack = make_app_stack(tmp_path)
    project_id = _create_project(stack)
    task_id = _make_failed_retryable(stack, project_id)

    await stack.app.restart_task(task_id)
    with pytest.raises(HTTPException) as exc_info:
        await task_routes.restart_task(task_id, app=stack.app)
    assert exc_info.value.status_code == 409
    assert cast(dict[str, Any], exc_info.value.detail)["code"] == "TASK_ALREADY_RETRIED"


async def test_app_restart_rechecks_status_inside_lock(tmp_path: Path):
    """初次读取可重试 → 等待锁期间状态被改为不可重试 → 获锁后必须拒绝。"""
    stack = make_app_stack(tmp_path)
    project_id = _create_project(stack)
    task_id = _make_failed_retryable(stack, project_id)

    lock = stack.app._restart_locks[task_id]
    await lock.acquire()
    try:
        # 启动重试：初始读取通过（FAILED 可重试），随后阻塞在锁上。
        pending = asyncio.create_task(stack.app.restart_task(task_id))
        await asyncio.sleep(0.05)
        # 锁外改写状态为不可重试，模拟等待期间的竞态。
        cast(TaskSQLiteStorage, stack.lifecycle.storage).update_task(task_id, status="running")
    finally:
        lock.release()

    with pytest.raises(TaskAppError) as exc_info:
        await pending
    assert exc_info.value.code == "TASK_NOT_RETRYABLE"


def test_db_unique_index_blocks_second_child(tmp_path: Path):
    """两个独立 storage 实例同时写同一父任务的子任务 → 仅一个成功。

    绕过应用层锁，直接验证数据库部分唯一索引本身构成数据不变量。
    """
    db_path = tmp_path / "argus.db"
    storage1 = TaskSQLiteStorage(db_path)
    storage2 = TaskSQLiteStorage(db_path)

    parent = Task(goal="目标", name="任务")
    storage1.save(parent)

    child1 = Task(
        goal=parent.goal,
        name=parent.name,
        execution_attempt=2,
        retry_parent_task_id=parent.task_id,
    )
    storage1.save(child1)

    child2 = Task(
        goal=parent.goal,
        name=parent.name,
        execution_attempt=2,
        retry_parent_task_id=parent.task_id,
    )
    with pytest.raises(TaskRetryConflictError):
        storage2.save(child2)


async def test_delete_child_reopens_parent_retry(tmp_path: Path):
    """删除未运行的 retry 子任务（规则 B）：父任务重新获得重试资格。"""
    stack = make_app_stack(tmp_path)
    project_id = _create_project(stack)
    task_id = _make_failed_retryable(stack, project_id)

    child, _ = await stack.app.restart_task(task_id)
    assert stack.app._lifecycle.has_retry_child(task_id) is True

    # 子任务处于 pending 且未入队，可删除。
    stack.app._lifecycle.delete_pending_task(child.task_id)
    assert stack.app._lifecycle.has_retry_child(task_id) is False

    # 父任务重新可重试。
    new_child, _ = await stack.app.restart_task(task_id)
    assert new_child.execution_attempt == 2


# ── 编辑三态 ─────────────────────────────────────────────────────────────────


# 除 name 外的固定更新参数
_UPDATE_BASE: dict[str, Any] = {
    "goal": "目标",
    "start_url": None,
    "task_type": TaskType.BLACKBOX,
    "project_id": None,
    "max_steps": 5,
    "timeout_seconds": 60,
    "capture_screenshots": False,
    "parameters": {},
}


def _update_info(lifecycle: TaskLifecycleService, task: Task) -> Task:
    """以除 name 外全固定的参数更新任务，供三态断言复用。"""
    return lifecycle.update_task_info(task, **_UPDATE_BASE)


def test_update_task_info_three_state_name(tmp_path: Path):
    lifecycle = TaskLifecycleService(TaskSQLiteStorage(tmp_path / "argus.db"), event_publisher=None)
    task = lifecycle.create_task(goal="目标", name="原名称")

    # 未提供 name → 保持原名
    updated = _update_info(lifecycle, task)
    assert updated.name == "原名称"

    # 显式 None / 空串 / 纯空白 → ID 兜底
    for cleared in (None, "", "   "):
        task.name = "原名称"
        updated = lifecycle.update_task_info(task, name=cleared, **_UPDATE_BASE)
        assert updated.name == task.task_id[-8:]

    # 正常值 → 去除首尾空白后使用
    task.name = "原名称"
    updated = lifecycle.update_task_info(task, name="  新名称  ", **_UPDATE_BASE)
    assert updated.name == "新名称"


async def test_update_route_omitted_name_keeps_original(tmp_path: Path):
    """PUT 未携带 name 字段时保持原名（三态语义经路由的参数裁剪）。"""
    stack = make_app_stack(tmp_path)
    project_id = _create_project(stack)
    req = TaskCreateRequest(project_id=project_id, goal="重试链任务", capture_screenshots=False)
    params = stack.app.resolve_create_params(
        goal=req.goal,
        name=req.name,
        start_url=req.start_url,
        task_type=req.task_type,
        project_id=req.project_id,
        max_steps=req.max_steps,
        timeout_seconds=req.timeout_seconds,
        capture_screenshots=req.capture_screenshots,
        model_config_id=req.model_config_id,
        parameters=req.parameters,
        whitebox_config=req.whitebox_config,
    )
    task = stack.app.create_task(**params)

    # 请求体不含 name（TaskUpdateRequest 默认 name=None，model_fields_set 无 name）
    update_req = TaskUpdateRequest(
        project_id=project_id, goal="更新后目标", capture_screenshots=False
    )
    updated = await task_routes.update_task(update_req, task.task_id, app=stack.app)
    assert updated.name == task.name  # 原名保持
    assert updated.goal == "更新后目标"


# ── API 契约：executionAttempt ───────────────────────────────────────────────


def test_task_response_exposes_execution_attempt(tmp_path: Path):
    stack = make_app_stack(tmp_path)
    project_id = _create_project(stack)
    task = stack.lifecycle.create_task(goal="目标", name="任务", project_id=project_id)

    detail = TaskResponse.from_task(task)
    assert detail.execution_attempt == 1
    assert detail.model_dump(by_alias=True)["executionAttempt"] == 1

    summary = TaskSummaryResponse.from_task(task)
    assert summary.execution_attempt == 1
    assert summary.model_dump(by_alias=True)["executionAttempt"] == 1


async def test_list_summary_path_carries_attempt(tmp_path: Path):
    """列表摘要查询路径的 attempt 不为 1 的回归测试。"""
    stack = make_app_stack(tmp_path)
    project_id = _create_project(stack)
    task_id = _make_failed_retryable(stack, project_id)
    child, _ = await stack.app.restart_task(task_id)

    tasks, _ = stack.reader.list_task_summaries()
    child_summary = next(t for t in tasks if t.task_id == child.task_id)
    assert child_summary.execution_attempt == 2
