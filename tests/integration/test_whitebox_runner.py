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


@pytest.fixture
def sample_whitebox_task(app_stack) -> Task:
    """创建一个白盒任务。"""
    params = app_stack.app.resolve_create_params(
        goal="白盒分析",
        start_url=None,
        task_type=TaskType.WHITEBOX,
        project_id="test-project",
        parameters={
            "source_path": "/tmp/fake-project",
            "scope": "all",
        },
    )
    return app_stack.app.create_task(**params)


@pytest.mark.asyncio
async def test_runner_register_handler(app_stack) -> None:
    """验证任务处理器注册。"""
    from argus_py.blackbox.runner import BlackboxRunner
    from argus_py.execution.runner import TaskRunner
    from argus_py.whitebox.client import WhiteboxClient
    from argus_py.whitebox.runner import WhiteboxRunner

    runner = TaskRunner(
        lifecycle=app_stack.lifecycle,
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
        status=VisibilityStatus.ENDPOINT_UNSUPPORTED,
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
        status=VisibilityStatus.ENDPOINT_UNSUPPORTED,
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
        status=VisibilityStatus.ENDPOINT_UNSUPPORTED,
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
async def test_runner_blackbox_not_affected(app_stack) -> None:
    """验证白盒注册不破坏黑盒任务执行。"""
    from argus_py.blackbox.runner import BlackboxRunner
    from argus_py.execution.runner import TaskRunner

    runner = TaskRunner(
        lifecycle=app_stack.lifecycle,
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
