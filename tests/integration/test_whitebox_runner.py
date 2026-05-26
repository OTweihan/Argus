"""白盒 Runner 集成测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from argus_py.core.enums import TaskType
from argus_py.core.exceptions import TaskError
from argus_py.task.models import Task


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
    from argus_py.execution.runner import TaskRunner
    from argus_py.whitebox.runner import WhiteboxRunner

    runner = TaskRunner(
        lifecycle=app_stack.lifecycle,
        reader=app_stack.reader,
    )

    assert TaskType.WHITEBOX in runner.handlers
    assert isinstance(runner.handlers[TaskType.WHITEBOX], type(WhiteboxRunner().run))
    assert callable(runner.handlers[TaskType.WHITEBOX])


@pytest.mark.asyncio
async def test_runner_whitebox_no_source(app_stack) -> None:
    """验证未提供源码路径时 runner 报错。"""
    from argus_py.execution.runner import TaskRunner

    task = Task(
        task_type=TaskType.WHITEBOX,
        project_id="test",
        goal="分析",
        parameters={},
    )
    app_stack.lifecycle.save_task(task)

    runner = TaskRunner(
        lifecycle=app_stack.lifecycle,
        reader=app_stack.reader,
    )

    with pytest.raises(TaskError, match="repo_url 或 source_path"):
        await runner.run(task)


@pytest.mark.asyncio
async def test_runner_whitebox_with_mock_client(app_stack) -> None:
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
    from argus_py.whitebox.source_resolver import SourceResolver

    mock_client = AsyncMock(spec=WhiteboxClient)
    mock_client.analyze.return_value = WhiteboxResult(
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

    mock_resolver = AsyncMock(spec=SourceResolver)
    mock_resolver.resolve_path.return_value = "/tmp/fake-project"

    whitebox_runner = WhiteboxRunner(
        client=mock_client,
        source_resolver=mock_resolver,
    )

    task = Task(
        task_type=TaskType.WHITEBOX,
        project_id="test",
        goal="白盒分析",
        parameters={
            "source_path": "/tmp/fake-project",
            "scope": "all",
        },
    )

    result = await whitebox_runner.run(task)

    assert result.task_type == TaskType.WHITEBOX
    assert len(result.findings) == 1
    assert result.findings[0].title == "空 catch 块"
    assert result.findings[0].location == "src/main/java/com/example/BadCode.java:12"
    assert result.result_summary is not None
    assert "端点" in result.result_summary
    assert "缺陷" in result.result_summary

    # 验证 parameters 中有全量结果
    wb = result.parameters.get("_whitebox_result", {})
    assert len(wb.get("endpoints", [])) == 1
    assert len(wb.get("callGraph", {})) == 1


@pytest.mark.asyncio
async def test_runner_blackbox_not_affected(app_stack) -> None:
    """验证白盒注册不破坏黑盒任务执行。"""
    from argus_py.execution.runner import TaskRunner

    runner = TaskRunner(
        lifecycle=app_stack.lifecycle,
        reader=app_stack.reader,
    )

    assert TaskType.BLACKBOX in runner.handlers
    assert TaskType.WHITEBOX in runner.handlers


@pytest.mark.asyncio
async def test_whitebox_task_api_validation(app_stack) -> None:
    """验证 API 层白盒任务创建参数校验。"""
    from argus_py.api.schemas.tasks import TaskCreateRequest

    # WHITEBOX 不带 repo_url/source_path 应报错
    with pytest.raises(ValueError, match="repo_url 或 source_path"):
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
