"""TaskApplicationService 专属单元测试。

补齐 O-11 分层收敛后遗留的覆盖缺口（此前只经集成测试间接验证）：

- ``resolve_create_params`` 黑盒/白盒分支与项目默认值合并
- ``start/cancel/pause/resume/update/delete`` 的状态机守卫（TaskAppError 分支）
- ``bind_analysis`` / ``retry_correlation`` / ``recalculate_correlation`` 早退分支
- 关联匹配失败时的 attempt 回滚（FAILED + re-raise）
- ``_chunked_batch`` 分片边界
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from argus_py.analysis.models import AnalysisRun
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
from argus_py.correlation.enums import BlackboxRunStatus, CorrelationRunStatus
from argus_py.correlation.models import BlackboxRun
from argus_py.correlation.report_data import chunked_batch
from argus_py.task.application import TaskAppError
from argus_py.task.models import Task
from argus_py.task.storage import TaskSQLiteStorage
from argus_py.whitebox.config import SourceType, WhiteboxTaskConfig

from tests.factories.correlation import make_correlation_run
from tests.helpers.factories import AppStack, make_app_stack

# ── resolve_create_params ─────────────────────────────────────────────────────


def test_resolve_create_params_blackbox_requires_start_url(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    # 无项目 base_url 且未传 start_url → 黑盒任务必须提供起始 URL
    with pytest.raises(TaskError, match="startUrl"):
        stack.app.resolve_create_params(goal="目标", task_type=TaskType.BLACKBOX)


def test_resolve_create_params_blackbox_rejects_malformed_url(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    with pytest.raises(TaskError, match="校验失败"):
        stack.app.resolve_create_params(
            goal="目标", start_url="not-a-url", task_type=TaskType.BLACKBOX
        )


def test_resolve_create_params_blackbox_merges_project_defaults(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    project = stack.project_service.create_project(
        name="项目",
        base_url="https://example.com",
        default_max_steps=7,
        default_timeout_seconds=90,
        default_capture_screenshots=False,
    )

    params = stack.app.resolve_create_params(
        goal="目标",
        task_type=TaskType.BLACKBOX,
        project_id=project.project_id,
    )

    assert params["start_url"] == "https://example.com"
    assert params["max_steps"] == 7
    assert params["timeout_seconds"] == 90
    assert params["capture_screenshots"] is False


def test_resolve_create_params_whitebox_builds_persisted_config(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    project = stack.project_service.create_project(name="项目", base_url="https://example.com")

    params = stack.app.resolve_create_params(
        goal="白盒",
        task_type=TaskType.WHITEBOX,
        project_id=project.project_id,
        whitebox_config=WhiteboxTaskConfig(source_type=SourceType.LOCAL, source_path="/tmp/src"),
    )

    assert params["whitebox_config_json"]  # 白盒配置已持久化
    assert params["task_type"] == TaskType.WHITEBOX
    assert params["max_steps"] == 1  # 白盒执行限制固定 1 步
    assert params["timeout_seconds"] == 3600


def test_resolve_create_params_whitebox_merges_scope_target_modules(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    project = stack.project_service.create_project(
        name="项目",
        base_url="https://example.com",
        parameters={"scope": "modules", "target_modules": ["app", "common"]},
    )

    params = stack.app.resolve_create_params(
        goal="白盒",
        task_type=TaskType.WHITEBOX,
        project_id=project.project_id,
        whitebox_config=WhiteboxTaskConfig(source_type=SourceType.LOCAL, source_path="/tmp/src"),
    )

    # 项目默认 scope/target_modules 应合并进最终 parameters
    assert params["parameters"]["scope"] == "modules"
    assert params["parameters"]["target_modules"] == ["app", "common"]


def test_resolve_create_params_whitebox_ignores_project_browser_defaults(tmp_path: Path) -> None:
    """白盒是单步分析，不继承项目的浏览器默认执行限制（max_steps/timeout）。

    锁定修复后的语义：项目默认执行限制只对黑盒合并；白盒仍固定兜底值。
    """
    stack = make_app_stack(tmp_path)
    project = stack.project_service.create_project(
        name="项目",
        base_url="https://example.com",
        default_max_steps=7,
        default_timeout_seconds=90,
    )

    params = stack.app.resolve_create_params(
        goal="白盒",
        task_type=TaskType.WHITEBOX,
        project_id=project.project_id,
        whitebox_config=WhiteboxTaskConfig(source_type=SourceType.LOCAL, source_path="/tmp/src"),
    )

    assert params["max_steps"] == 1
    assert params["timeout_seconds"] == 3600


# ── 状态机守卫（TaskAppError 分支）────────────────────────────────────────────


def _create_task(stack: AppStack, status: TaskStatus = TaskStatus.PENDING) -> Task:
    task = stack.lifecycle.create_task(goal="目标", name="任务")
    if status == TaskStatus.PENDING:
        return task
    # 合法转换路径：PENDING → RUNNING → 目标状态
    stack.lifecycle.update_status(task, TaskStatus.RUNNING)
    if status != TaskStatus.RUNNING:
        stack.lifecycle.update_status(task, status)
    return task


async def test_start_task_rejects_non_pending(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    task = _create_task(stack, TaskStatus.RUNNING)

    with pytest.raises(TaskAppError) as exc_info:
        await stack.app.start_task(task.task_id)
    assert exc_info.value.code == "TASK_NOT_PENDING"


async def test_cancel_task_rejects_terminal(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    task = _create_task(stack, TaskStatus.FAILED)

    with pytest.raises(TaskAppError) as exc_info:
        await stack.app.cancel_task(task.task_id)
    assert exc_info.value.code == "TASK_ALREADY_FINISHED"


async def test_pause_task_rejects_non_running(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    task = _create_task(stack, TaskStatus.PENDING)

    with pytest.raises(TaskAppError) as exc_info:
        await stack.app.pause_task(task.task_id)
    assert exc_info.value.code == "TASK_NOT_RUNNING"


async def test_resume_task_rejects_non_paused(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    task = _create_task(stack, TaskStatus.RUNNING)

    with pytest.raises(TaskAppError) as exc_info:
        await stack.app.resume_task(task.task_id)
    assert exc_info.value.code == "TASK_NOT_PAUSED"


async def test_resume_task_rejects_when_handler_not_executing(tmp_path: Path) -> None:
    """PAUSED 但执行器已退出（队列无活跃记录）→ resume 被拒（僵尸防护）。

    白盒是一次性分析型 handler：暂停后远端作业完成、结果落盘但被 PAUSED
    阻止终态推进时，handler 已退出；此时 resume 只会产出永远无人执行的假
    RUNNING 任务。
    """
    stack = make_app_stack(tmp_path)
    task = _create_task(stack, TaskStatus.PAUSED)

    with pytest.raises(TaskAppError) as exc_info:
        await stack.app.resume_task(task.task_id)
    assert exc_info.value.code == "TASK_NOT_EXECUTING"
    # 状态保持 PAUSED，未翻回 RUNNING
    refreshed = stack.lifecycle.storage.load(task.task_id)
    assert refreshed.status == TaskStatus.PAUSED


async def test_resume_task_allows_when_execution_active(tmp_path: Path) -> None:
    """PAUSED 且 handler 仍在执行（队列活跃记录存在）→ resume 正常放行。"""
    stack = make_app_stack(tmp_path)
    task = _create_task(stack, TaskStatus.PAUSED)

    # 模拟 worker 已认领该任务（进入队列活跃集合）
    await stack.queue.enqueue(task.task_id)
    assert await stack.queue.get() == task.task_id

    resumed = await stack.app.resume_task(task.task_id)
    assert resumed.status == TaskStatus.RUNNING

    await stack.queue.complete(task.task_id)


async def test_update_task_rejects_non_editable(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    task = _create_task(stack, TaskStatus.RUNNING)

    with pytest.raises(TaskAppError) as exc_info:
        await stack.app.update_task(task.task_id, {"goal": "新目标"})
    assert exc_info.value.code == "TASK_NOT_EDITABLE"


async def test_delete_task_rejects_non_deletable(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    task = _create_task(stack, TaskStatus.RUNNING)

    with pytest.raises(TaskAppError) as exc_info:
        await stack.app.delete_task(task.task_id)
    assert exc_info.value.code == "TASK_NOT_DELETABLE"


# ── 关联操作早退分支 ──────────────────────────────────────────────────────────


def _seed_base(stack: AppStack) -> str:
    """创建 project + task(t-1) + blackbox_run(bb-1)，返回 project_id。

    correlation_runs 有 project_id 与 blackbox_run_id 外键，blackbox_runs 有
    task_id 外键，故绑定/重试等关联操作前必须先建立这三层。幂等：同栈内重复
    调用（如一个测试同时 seed analysis_run 与 correlation_run）复用已建实体。
    """
    storage = stack.lifecycle.storage
    assert isinstance(storage, TaskSQLiteStorage)
    existing = storage.load_task_header("t-1")
    if existing is not None:
        return existing["project_id"]
    project_id = stack.project_service.create_project(
        name="项目", base_url="https://example.com"
    ).project_id
    storage.save(
        Task(
            task_id="t-1",
            goal="g",
            project_id=project_id,
            task_type=TaskType.BLACKBOX,
            status=TaskStatus.PENDING,
        )
    )
    storage.create_blackbox_run(
        BlackboxRun(
            blackbox_run_id="bb-1",
            task_id="t-1",
            attempt=1,
            status=BlackboxRunStatus.SUCCESS,
            started_at="2024-01-01T00:00:00",
        )
    )
    return project_id


def _seed_analysis_run(stack: AppStack, analysis_id: str, *, run_status: str = "SUCCEEDED") -> str:
    """创建 analysis_run（含 base 依赖），返回 project_id。"""
    project_id = _seed_base(stack)  # bind_analysis 会 load_task_header，需 task 存在
    storage = stack.lifecycle.storage
    assert isinstance(storage, TaskSQLiteStorage)
    storage.create_analysis_run(
        AnalysisRun(
            analysis_id=analysis_id,
            task_id="t-1",
            source_snapshot_id="src-1",
            resolved_commit_sha="abc123",
            run_status=run_status,
            config_json="{}",
        )
    )
    return project_id


def _seed_correlation_run(
    stack: AppStack,
    correlation_run_id: str,
    *,
    analysis_id: str | None,
    status: CorrelationRunStatus,
) -> None:
    project_id = _seed_base(stack)
    storage = stack.lifecycle.storage
    assert isinstance(storage, TaskSQLiteStorage)
    storage.create_correlation_run(
        make_correlation_run(
            correlation_run_id=correlation_run_id,
            project_id=project_id,
            blackbox_run_id="bb-1",
            analysis_id=analysis_id,
            status=status,
        )
    )


def test_bind_analysis_rejects_missing_analysis(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    _seed_correlation_run(
        stack, "cr-1", analysis_id=None, status=CorrelationRunStatus.WAITING_BINDING
    )

    with pytest.raises(ValueError, match="分析执行不存在"):
        stack.correlation.bind_analysis("cr-1", "analysis-missing")


def test_bind_analysis_rejects_non_succeeded_analysis(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    _seed_analysis_run(stack, "analysis-1", run_status="FAILED")
    _seed_correlation_run(
        stack, "cr-1", analysis_id=None, status=CorrelationRunStatus.WAITING_BINDING
    )

    with pytest.raises(ValueError, match="只有成功的分析可以绑定"):
        stack.correlation.bind_analysis("cr-1", "analysis-1")


def test_bind_analysis_rejects_missing_correlation_run(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    _seed_analysis_run(stack, "analysis-1")

    with pytest.raises(ValueError, match="关联运行不存在"):
        stack.correlation.bind_analysis("cr-missing", "analysis-1")


def test_bind_analysis_rejects_already_bound(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    _seed_analysis_run(stack, "analysis-1")
    _seed_correlation_run(
        stack, "cr-1", analysis_id="analysis-0", status=CorrelationRunStatus.READY
    )

    with pytest.raises(ValueError, match="已绑定分析"):
        stack.correlation.bind_analysis("cr-1", "analysis-1")


def test_bind_analysis_rejects_snapshot_mismatch_without_override(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    project_id = _seed_analysis_run(stack, "analysis-1")  # resolved_commit_sha=abc123
    storage = stack.lifecycle.storage
    assert isinstance(storage, TaskSQLiteStorage)
    # 期望快照与 analysis 实际快照不一致
    storage.create_correlation_run(
        make_correlation_run(
            correlation_run_id="cr-1",
            project_id=project_id,
            blackbox_run_id="bb-1",
            analysis_id=None,
            desired_source_snapshot_id="different-sha",
            status=CorrelationRunStatus.WAITING_BINDING,
        )
    )

    with pytest.raises(ValueError, match="不一致"):
        stack.correlation.bind_analysis("cr-1", "analysis-1")


def test_retry_correlation_rejects_missing_run(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    with pytest.raises(ValueError, match="关联运行不存在"):
        stack.correlation.retry_correlation("cr-missing")


def test_retry_correlation_rejects_non_failed_partial(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    _seed_correlation_run(
        stack, "cr-1", analysis_id="analysis-1", status=CorrelationRunStatus.READY
    )

    with pytest.raises(ValueError, match="只有失败或部分完成"):
        stack.correlation.retry_correlation("cr-1")


def test_retry_correlation_rejects_unbound(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    _seed_correlation_run(stack, "cr-1", analysis_id=None, status=CorrelationRunStatus.FAILED)

    with pytest.raises(ValueError, match="尚未绑定白盒分析"):
        stack.correlation.retry_correlation("cr-1")


def test_recalculate_correlation_returns_none_for_missing_run(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    assert stack.correlation.recalculate_correlation("cr-missing") is None


def test_recalculate_correlation_rejects_unbound(tmp_path: Path) -> None:
    stack = make_app_stack(tmp_path)
    _seed_correlation_run(stack, "cr-1", analysis_id=None, status=CorrelationRunStatus.READY)

    with pytest.raises(ValueError, match="尚未绑定白盒分析"):
        stack.correlation.recalculate_correlation("cr-1")


def test_retry_correlation_marks_attempt_failed_and_reraises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关联匹配异常时 attempt 落 FAILED/PARTIAL 并原样 re-raise（不静默吞错）。"""
    stack = make_app_stack(tmp_path)
    storage = stack.lifecycle.storage
    assert isinstance(storage, TaskSQLiteStorage)
    _seed_correlation_run(
        stack, "cr-1", analysis_id="analysis-1", status=CorrelationRunStatus.FAILED
    )

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("match exploded")

    monkeypatch.setattr("argus_py.correlation.application._execute_matching_sync", boom)

    complete_calls: list[tuple[str, str, str]] = []
    original = storage.complete_and_activate_attempt

    def spy(attempt_id: str, status: str, completeness: str = "COMPLETE") -> None:
        complete_calls.append((attempt_id, status, completeness))
        original(attempt_id, status, completeness)

    monkeypatch.setattr(storage, "complete_and_activate_attempt", spy)

    with pytest.raises(RuntimeError, match="match exploded"):
        stack.correlation.retry_correlation("cr-1")

    assert complete_calls
    assert complete_calls[-1][1] == "FAILED"
    assert complete_calls[-1][2] == "PARTIAL"


# ── chunked_batch 分片边界 ───────────────────────────────────────────────────


def test_chunked_batch_empty_ids_no_calls() -> None:
    batch_fn = Mock(return_value={})
    assert chunked_batch(batch_fn, []) == {}
    batch_fn.assert_not_called()


def test_chunked_batch_single_chunk() -> None:
    def batch_fn(ids: list[str]) -> dict[str, Any]:
        return {i: int(i) * 2 for i in ids}

    assert chunked_batch(batch_fn, ["1", "2", "3"], chunk_size=800) == {
        "1": 2,
        "2": 4,
        "3": 6,
    }


def test_chunked_batch_crosses_boundary_and_merges() -> None:
    calls: list[list[str]] = []

    def batch_fn(ids: list[str]) -> dict[str, Any]:
        calls.append(ids)
        return {i: i for i in ids}

    ids = [str(i) for i in range(5)]
    result = chunked_batch(batch_fn, ids, chunk_size=2)

    assert calls == [["0", "1"], ["2", "3"], ["4"]]
    assert result == {str(i): str(i) for i in range(5)}


def test_chunked_batch_exact_multiple_of_chunk_size() -> None:
    calls: list[list[str]] = []

    def batch_fn(ids: list[str]) -> dict[str, Any]:
        calls.append(ids)
        return {}

    chunked_batch(batch_fn, ["a", "b", "c", "d"], chunk_size=2)
    assert calls == [["a", "b"], ["c", "d"]]
