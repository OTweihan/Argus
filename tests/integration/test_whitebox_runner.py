"""白盒 Runner 集成测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from argus_py.core.enums import TaskType
from argus_py.core.exceptions import TaskError
from argus_py.task.event import TaskTimelineService
from argus_py.task.log import TaskLogService
from argus_py.task.models import Task
from argus_py.task.storage import TaskSQLiteStorage


@pytest.mark.asyncio
async def test_runner_register_handler(app_stack) -> None:
    """验证任务处理器注册。"""
    from argus_py.blackbox.runner import BlackboxRunner
    from argus_py.execution.runner import TaskRunner
    from argus_py.report.generator import ReportGenerator
    from argus_py.whitebox.client import WhiteboxClient
    from argus_py.whitebox.runner import WhiteboxRunner

    runner = TaskRunner(
        lifecycle=app_stack.lifecycle,
        report_generator=ReportGenerator(),
        handlers={
            TaskType.BLACKBOX: BlackboxRunner(
                lifecycle=app_stack.lifecycle,
                reader=app_stack.reader,
                log_service=TaskLogService(TaskSQLiteStorage()),
                timeline_service=TaskTimelineService(TaskSQLiteStorage()),
                model_config_service=None,
            ).run,
            TaskType.WHITEBOX: WhiteboxRunner(
                client=AsyncMock(spec=WhiteboxClient),
                timeline_service=app_stack.timeline,
                lifecycle=app_stack.lifecycle,
            ).run,
        },
    )

    assert TaskType.WHITEBOX in runner.handlers
    assert TaskType.BLACKBOX in runner.handlers
    assert callable(runner.handlers[TaskType.WHITEBOX])


@pytest.mark.asyncio
async def test_runner_whitebox_no_source(app_stack) -> None:
    """验证未提供源码路径时 runner 报错。"""
    from argus_py.execution.runner import TaskRunner
    from argus_py.report.generator import ReportGenerator
    from argus_py.whitebox.client import WhiteboxClient
    from argus_py.whitebox.runner import WhiteboxRunner

    task = Task(
        task_type=TaskType.WHITEBOX,
        project_id="test",
        goal="分析",
        parameters={},
    )
    app_stack.lifecycle.save_task(task)

    runner = TaskRunner(
        lifecycle=app_stack.lifecycle,
        report_generator=ReportGenerator(),
        handlers={
            TaskType.WHITEBOX: WhiteboxRunner(
                client=AsyncMock(spec=WhiteboxClient),
                timeline_service=app_stack.timeline,
                lifecycle=app_stack.lifecycle,
            ).run,
        },
    )

    with pytest.raises(TaskError, match="source_path"):
        await runner.run(task)


@pytest.mark.asyncio
async def test_runner_whitebox_with_mock_client(app_stack, tmp_path) -> None:
    """验证 mock Java 客户端后 runner 正确产出 findings。"""
    from argus_py.whitebox.client import WhiteboxClient
    from argus_py.whitebox.models import (
        CallGraph,
        CallGraphNode,
        Endpoint,
        WhiteboxFinding,
        WhiteboxResult,
    )
    from argus_py.whitebox.runner import WhiteboxRunner
    from argus_py.whitebox.source_resolver import ResolvedSource, SourceResolver

    mock_client = AsyncMock(spec=WhiteboxClient)
    mock_client.request_timeout = 30.0  # property value for poll loop
    # Async flow: submit → poll → result
    from argus_py.whitebox.models import WhiteboxJobStatus

    mock_client.submit_analyze_job.return_value = WhiteboxJobStatus(
        job_id="test-job-001", status="PENDING"
    )
    mock_client.get_analyze_job.return_value = WhiteboxJobStatus(
        job_id="test-job-001", status="SUCCEEDED"
    )
    from argus_py.whitebox.client import SourceVisibilityResult, VisibilityStatus

    mock_client.validate_source.return_value = SourceVisibilityResult(
        status=VisibilityStatus.VALIDATED,
        exists=True,
        readable=True,
    )
    mock_client.get_analyze_job_result.return_value = WhiteboxResult(
        endpoints=[
            Endpoint(
                path="/api/users",
                http_method="GET",
                controller_class="com.example.UserController",
                controller_method="listUsers",
            ),
        ],
        call_graph=CallGraph(
            nodes={
                "com.example.UserController#listUsers": CallGraphNode(
                    class_name="com.example.UserController",
                    method_name="listUsers",
                    method_signature="List<User> listUsers()",
                    callee_details=[],
                ),
            }
        ),
        findings=[
            WhiteboxFinding(
                rule_id="EMPTY_CATCH",
                severity="MEDIUM",
                title="空 catch 块",
                description="catch 块为空",
                file_path="src/main/java/com/example/BadCode.java",
                line_number=12,
            ),
        ],
    )

    fake_path = str(tmp_path)
    from unittest.mock import MagicMock

    mock_resolver = MagicMock(spec=SourceResolver)
    mock_resolver.resolve_path.return_value = ResolvedSource(
        source_type="local",
        resolved_path=fake_path,
        requested_ref=None,
        resolved_commit_sha=None,
        ref_type=None,
        is_dirty=None,
    )

    whitebox_runner = WhiteboxRunner(
        client=mock_client,
        source_resolver=mock_resolver,
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
    )

    task = Task(
        task_type=TaskType.WHITEBOX,
        project_id="test",
        goal="白盒分析",
        parameters={
            "source_path": fake_path,
            "scope": "all",
        },
    )
    # Task must be saved for timeline FK constraint
    app_stack.lifecycle.save_task(task)

    await whitebox_runner.run(task)

    assert task.task_type == TaskType.WHITEBOX
    assert len(task.findings) == 1
    assert task.findings[0].title == "空 catch 块"
    assert task.findings[0].location == "src/main/java/com/example/BadCode.java:12"
    assert task.result_summary is not None
    assert "端点" in task.result_summary
    assert "缺陷" in task.result_summary

    # 验证 result_json 中有全量结果
    wb = json.loads(task.result_json or "{}")
    assert len(wb.get("endpoints", [])) == 1
    assert len(wb.get("callGraph", {})) == 1
    mock_resolver.release.assert_called_once()


@pytest.mark.asyncio
async def test_whitebox_runner_closes_injected_client(monkeypatch, tmp_path, app_stack) -> None:
    from unittest.mock import MagicMock

    from argus_py.whitebox.models import CallGraph, WhiteboxResult
    from argus_py.whitebox.runner import WhiteboxRunner
    from argus_py.whitebox.source_resolver import ResolvedSource, SourceResolver

    mock_client = AsyncMock()
    # Async flow: submit → poll → result
    from argus_py.whitebox.models import WhiteboxJobStatus

    mock_client.submit_analyze_job.return_value = WhiteboxJobStatus(
        job_id="test-job", status="PENDING"
    )
    mock_client.get_analyze_job.return_value = WhiteboxJobStatus(
        job_id="test-job", status="SUCCEEDED"
    )
    mock_client.get_analyze_job_result.return_value = WhiteboxResult(call_graph=CallGraph(nodes={}))
    mock_client.request_timeout = 30.0
    from argus_py.whitebox.client import SourceVisibilityResult, VisibilityStatus

    mock_client.validate_source.return_value = SourceVisibilityResult(
        status=VisibilityStatus.VALIDATED,
        exists=True,
        readable=True,
    )

    resolver = MagicMock(spec=SourceResolver)
    resolver.resolve_path.return_value = ResolvedSource(
        source_type="local",
        resolved_path=str(tmp_path),
        requested_ref=None,
        resolved_commit_sha=None,
        ref_type=None,
        is_dirty=None,
    )

    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="白盒分析",
        parameters={"source_path": str(tmp_path)},
    )
    app_stack.lifecycle.save_task(task)  # needed for FK

    await WhiteboxRunner(
        client=mock_client,
        source_resolver=resolver,
        timeline_service=app_stack.timeline,
        lifecycle=app_stack.lifecycle,
    ).run(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("failed")])
async def test_whitebox_runner_failure_does_not_throw(
    monkeypatch, tmp_path, failure: BaseException, app_stack
) -> None:
    from unittest.mock import MagicMock

    from argus_py.whitebox.runner import WhiteboxRunner
    from argus_py.whitebox.source_resolver import ResolvedSource, SourceResolver

    mock_client = AsyncMock()
    mock_client.submit_analyze_job.side_effect = failure
    mock_client.request_timeout = 30.0
    from argus_py.whitebox.client import SourceVisibilityResult, VisibilityStatus

    mock_client.validate_source.return_value = SourceVisibilityResult(
        status=VisibilityStatus.VALIDATED,
        exists=True,
        readable=True,
    )

    resolver = MagicMock(spec=SourceResolver)
    resolver.resolve_path.return_value = ResolvedSource(
        source_type="local",
        resolved_path=str(tmp_path),
        requested_ref=None,
        resolved_commit_sha=None,
        ref_type=None,
        is_dirty=None,
    )

    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="白盒分析",
        parameters={"source_path": str(tmp_path)},
    )
    app_stack.lifecycle.save_task(task)  # needed for FK

    # Exception is re-raised by runner (wrapped by TaskRunner which we skip here)
    with pytest.raises(type(failure)):
        await WhiteboxRunner(
            client=mock_client,
            source_resolver=resolver,
            timeline_service=app_stack.timeline,
            lifecycle=app_stack.lifecycle,
        ).run(task)


@pytest.mark.asyncio
async def test_whitebox_runner_preserves_snapshot_when_remote_may_still_run(
    tmp_path, app_stack
) -> None:
    from unittest.mock import MagicMock

    from argus_py.whitebox.client import SourceVisibilityResult, VisibilityStatus, WhiteboxClient
    from argus_py.whitebox.exceptions import WhiteboxTaskCancelled
    from argus_py.whitebox.models import WhiteboxJobStatus
    from argus_py.whitebox.runner import WhiteboxRunner
    from argus_py.whitebox.source_resolver import ResolvedSource, SourceResolver

    mock_client = AsyncMock(spec=WhiteboxClient)
    mock_client.request_timeout = 30.0
    mock_client.validate_source.return_value = SourceVisibilityResult(
        status=VisibilityStatus.VALIDATED,
        exists=True,
        readable=True,
    )
    mock_client.submit_analyze_job.return_value = WhiteboxJobStatus(
        job_id="still-running", status="PENDING"
    )
    # O-04：远端取消端点不可用（模拟旧版 Java / 作业已过期）→ 无法确认 → 保留 STOPPED_WAITING
    mock_client.cancel_analyze_job.return_value = None
    resolver = MagicMock(spec=SourceResolver)
    resolver.resolve_path.return_value = ResolvedSource(
        source_type="local",
        resolved_path=str(tmp_path),
        requested_ref=None,
        resolved_commit_sha="snapshot",
        ref_type=None,
        is_dirty=None,
        managed_snapshot=True,
    )
    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="白盒分析",
        parameters={"source_path": str(tmp_path)},
    )
    app_stack.lifecycle.save_task(task)
    app_stack.lifecycle.get_cancellation_token(task.task_id).cancel()

    with pytest.raises(WhiteboxTaskCancelled):
        await WhiteboxRunner(
            client=mock_client,
            source_resolver=resolver,
            timeline_service=app_stack.timeline,
            lifecycle=app_stack.lifecycle,
            poll_interval=0,
            cancel_confirmation_timeout=0.0,
        ).run(task)

    resolver.release.assert_not_called()


@pytest.mark.asyncio
async def test_runner_blackbox_not_affected(app_stack) -> None:
    """验证白盒注册不破坏黑盒任务执行。"""
    from argus_py.blackbox.runner import BlackboxRunner
    from argus_py.execution.runner import TaskRunner
    from argus_py.report.generator import ReportGenerator

    runner = TaskRunner(
        lifecycle=app_stack.lifecycle,
        report_generator=ReportGenerator(),
        handlers={
            TaskType.BLACKBOX: BlackboxRunner(
                lifecycle=app_stack.lifecycle,
                reader=app_stack.reader,
                log_service=TaskLogService(TaskSQLiteStorage()),
                timeline_service=TaskTimelineService(TaskSQLiteStorage()),
                model_config_service=None,
            ).run,
        },
    )

    assert TaskType.BLACKBOX in runner.handlers


@pytest.mark.asyncio
async def test_whitebox_task_api_validation(app_stack) -> None:
    """验证 API 层白盒任务创建参数校验。"""
    from argus_py.api.schemas.tasks import TaskCreateRequest

    # WHITEBOX 不带 repo_url/source_path 应报错
    with pytest.raises(ValueError, match="白盒任务必须提供"):
        TaskCreateRequest(
            taskType="whitebox",
            project_id="test",
            goal="白盒分析",
            parameters={},
        )

    # WHITEBOX 带 source_path 应通过
    req = TaskCreateRequest(
        taskType="whitebox",
        project_id="test",
        goal="白盒分析",
        parameters={"source_path": "/tmp/test"},
    )
    assert req.task_type == TaskType.WHITEBOX
    assert req.parameters["source_path"] == "/tmp/test"

    # WHITEBOX 带 repo_url 应通过
    req = TaskCreateRequest(
        taskType="whitebox",
        project_id="test",
        goal="白盒分析",
        parameters={"repo_url": "https://github.com/user/repo.git"},
    )
    assert req.task_type == TaskType.WHITEBOX


@pytest.mark.asyncio
async def test_cancel_emits_timeline_event(app_stack, tmp_path) -> None:
    """取消白盒任务时应发出 whitebox_cancelled 时间线事件。"""
    from unittest.mock import AsyncMock, MagicMock

    from argus_py.whitebox.client import SourceVisibilityResult, VisibilityStatus, WhiteboxClient
    from argus_py.whitebox.exceptions import WhiteboxTaskCancelled
    from argus_py.whitebox.models import WhiteboxJobStatus
    from argus_py.whitebox.runner import WhiteboxRunner
    from argus_py.whitebox.source_resolver import ResolvedSource, SourceResolver

    mock_client = AsyncMock(spec=WhiteboxClient)
    mock_client.request_timeout = 30.0
    mock_client.validate_source.return_value = SourceVisibilityResult(
        status=VisibilityStatus.VALIDATED,
        exists=True,
        readable=True,
    )
    mock_client.submit_analyze_job.return_value = WhiteboxJobStatus(
        job_id="timeline-job", status="PENDING"
    )
    # O-04：远端取消端点不可用 → 无法确认 → origin 保持 local（STOPPED_WAITING）
    mock_client.cancel_analyze_job.return_value = None

    resolver = MagicMock(spec=SourceResolver)
    resolver.resolve_path.return_value = ResolvedSource(
        source_type="local",
        resolved_path=str(tmp_path),
        requested_ref=None,
        resolved_commit_sha=None,
        ref_type=None,
        is_dirty=None,
        managed_snapshot=True,
    )

    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="白盒分析",
        parameters={"source_path": str(tmp_path)},
    )
    app_stack.lifecycle.save_task(task)
    # 预置取消信号
    app_stack.lifecycle.get_cancellation_token(task.task_id).cancel()

    with pytest.raises(WhiteboxTaskCancelled):
        await WhiteboxRunner(
            client=mock_client,
            source_resolver=resolver,
            timeline_service=app_stack.timeline,
            lifecycle=app_stack.lifecycle,
            poll_interval=0,
            cancel_confirmation_timeout=0.0,
        ).run(task)

    # 验证时间线事件已发出
    events = app_stack.timeline.list_by_task(task.task_id)
    event_types = [e.event_type for e in events]
    assert "whitebox_cancelled" in event_types, (
        f"取消时应发出 whitebox_cancelled 事件，实际事件: {event_types}"
    )

    # 验证事件携带正确的 jobId 和 origin
    cancel_event = next(e for e in events if e.event_type == "whitebox_cancelled")
    assert cancel_event.data.get("jobId") == "timeline-job"
    assert cancel_event.data.get("origin") == "local"

    # 本地取消 → analysis_runs 落 STOPPED_WAITING（只停止等待，远端可能仍在运行），
    # 同时保留 failure_code 供诊断
    runs, _ = app_stack.lifecycle.storage.list_analysis_runs(task.task_id)
    assert len(runs) == 1
    assert runs[0].run_status == "STOPPED_WAITING"
    assert runs[0].failure_code == "WHITEBOX_TASK_CANCELLED"


@pytest.mark.asyncio
async def test_update_task_preserves_whitebox_config(app_stack) -> None:
    """更新白盒 pending 任务时 whitebox_config 不应被静默丢弃。"""
    from argus_py.whitebox.config import WhiteboxMavenConfig, WhiteboxTaskConfig

    # 1. 创建项目
    project = app_stack.project_service.create_project(
        name="update-test",
        description="test",
        base_url="https://example.com",
    )

    # 2. 创建白盒任务
    params = app_stack.app.resolve_create_params(
        goal="白盒分析",
        start_url=None,
        task_type=TaskType.WHITEBOX,
        project_id=project.project_id,
        whitebox_config=WhiteboxTaskConfig(
            source_type="local",  # type: ignore[arg-type]
            source_path="/tmp/original-path",
            scope="callgraph",
            target_modules=["mod-a"],
            maven=WhiteboxMavenConfig(classpath_mode="MAVEN", offline=True),  # type: ignore[arg-type]
        ),
    )
    task = app_stack.app.create_task(**params)

    # 验证初始持久化
    assert task.whitebox_config_json is not None
    saved = json.loads(task.whitebox_config_json)
    assert saved["source_path"] == "/tmp/original-path"
    assert saved["scope"] == "callgraph"
    assert saved["maven"]["classpath_mode"] == "MAVEN"
    assert saved["maven"]["offline"] is True

    # 2. 更新配置
    new_config = WhiteboxTaskConfig(
        source_type="local",  # type: ignore[arg-type]
        source_path="/tmp/updated-path",
        scope="endpoints",
        target_modules=["mod-b", "mod-c"],
    )
    updated_params = app_stack.app.resolve_create_params(
        goal="更新后的白盒分析",
        start_url=None,
        task_type=TaskType.WHITEBOX,
        project_id=project.project_id,
        whitebox_config=new_config,
    )
    updated_task, _ = await app_stack.app.update_task(task.task_id, updated_params)

    # 3. 验证更新后的持久化
    assert updated_task.whitebox_config_json is not None
    saved = json.loads(updated_task.whitebox_config_json)
    assert saved["source_path"] == "/tmp/updated-path"
    assert saved["scope"] == "endpoints"
    assert saved["target_modules"] == ["mod-b", "mod-c"]
    assert updated_task.goal == "更新后的白盒分析"


@pytest.mark.asyncio
async def test_maven_none_in_merge_does_not_crash(app_stack) -> None:
    """whiteboxConfig.maven=null 与项目默认 maven 合并时不应抛出 TypeError。

    复现条件：项目 parameters 中有 maven 默认值，任务 whiteboxConfig
    中 maven 字段为 None/未提供 → raw["maven"] 不存在或为 None，
    isinstance(raw["maven"], dict) 守卫应正确跳过合并。
    """
    from argus_py.whitebox.config import WhiteboxTaskConfig

    # 创建带 maven 默认值的项目
    project = app_stack.project_service.create_project(
        name="maven-test",
        description="test",
        base_url="https://example.com",
        parameters={
            "maven": {
                "classpath_mode": "CACHE_ONLY",
                "offline": True,
            },
        },
    )

    # whiteboxConfig 不含 maven → raw 中无 "maven" key
    params = app_stack.app.resolve_create_params(
        goal="白盒分析",
        start_url=None,
        task_type=TaskType.WHITEBOX,
        project_id=project.project_id,
        whitebox_config=WhiteboxTaskConfig(
            source_type="local",  # type: ignore[arg-type]
            source_path="/tmp/test-project",
            scope="all",
        ),
    )
    task = app_stack.app.create_task(**params)
    assert task.task_id

    # whiteboxConfig.maven 显式为 None → model_dump(exclude_unset=True) 后不存在
    params2 = app_stack.app.resolve_create_params(
        goal="白盒分析 2",
        start_url=None,
        task_type=TaskType.WHITEBOX,
        project_id=project.project_id,
        whitebox_config=WhiteboxTaskConfig(
            source_type="local",  # type: ignore[arg-type]
            source_path="/tmp/test-project-2",
            scope="all",
            maven=None,
        ),
    )
    task2 = app_stack.app.create_task(**params2)
    assert task2.task_id

    # 验证项目默认 maven 被正确合并到 parameters（两个分支行为一致）
    assert "maven" in task.parameters
    assert task.parameters["maven"]["classpath_mode"] == "CACHE_ONLY"
    assert task.parameters["maven"]["offline"] is True

    assert "maven" in task2.parameters
    assert task2.parameters["maven"]["classpath_mode"] == "CACHE_ONLY"
    assert task2.parameters["maven"]["offline"] is True
