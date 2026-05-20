import asyncio
from pathlib import Path

import pytest

from argus_py.api.routes import projects as project_routes
from argus_py.api.routes import tasks as task_routes
from argus_py.api.schemas import ProjectCreateRequest, TaskCreateRequest
from argus_py.cli import main as cli_main
from argus_py.core.enums import TaskStatus
from argus_py.infra.events import EventBus
from argus_py.infra.worker import TaskWorker
from argus_py.report.generator import ReportGenerator, generate_report_safely
from argus_py.task.models import Task
from tests.helpers.factories import make_app_stack


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.asyncio
async def test_web_platform_project_task_worker_events_and_report(tmp_path, monkeypatch):
    """覆盖项目创建、任务创建、入队、后台执行、事件推送和报告回写。"""
    event_bus = EventBus(history_limit=50)
    stack = make_app_stack(tmp_path, event_publisher=event_bus.publish)
    report_dir = tmp_path / "reports"

    class FakeTaskRunner:
        def __init__(self, service, model_config_service=None):
            self.service = service
            self._model_config_service = model_config_service

        async def run(self, task: Task) -> Task:
            running = self.service.start_task(task)
            logged = self.service.append_log(
                running,
                action="goto",
                url_after=running.start_url,
                message="端到端契约测试步骤。",
            )
            completed = self.service.complete_task(logged, result_summary="端到端契约测试完成。")
            return generate_report_safely(
                completed,
                ReportGenerator(report_dir),
                self.service.save_task,
            )

    monkeypatch.setattr("argus_py.infra.worker.TaskRunner", FakeTaskRunner)

    worker = TaskWorker(queue=stack.queue, service=stack.task_service)
    await worker.start()
    try:
        project = await project_routes.create_project(
            ProjectCreateRequest(
                name="E2E 项目",
                base_url="https://example.com",
                default_max_steps=3,
                default_timeout_seconds=30,
            ),
            service=stack.project_service,
        )
        task = await task_routes.create_task(
            TaskCreateRequest(
                project_id=project.project_id,
                goal="验证 Web 平台端到端契约",
                capture_screenshots=False,
            ),
            app=stack.app,
        )
        # create_task 经 asyncio.to_thread 在线程池执行，线程内无 running loop，
        # 事件降级写入 history 而非订阅队列。在此之后订阅并 replay，可补回该事件。
        subscription = await event_bus.subscribe(replay=True)

        start_result = await task_routes.start_task(task.task_id, app=stack.app)

        assert start_result.scheduler_status == "queued"
        completed = await _wait_for_task_status(
            stack.task_service, task.task_id, TaskStatus.COMPLETED
        )
        assert completed.current_step == 1
        assert completed.report_path is not None
        assert Path(completed.report_path).exists()

        await asyncio.sleep(0.05)
        event_types = await _drain_event_types(subscription)
        assert "task.created" in event_types
        assert "task.status" in event_types
        assert "task.log" in event_types
        assert "task.complete" in event_types
    finally:
        await subscription.close()
        await worker.stop(timeout_seconds=1)


@pytest.mark.slow
@pytest.mark.integration
def test_submitted_project_and_task_survive_service_recreation(tmp_path):
    """覆盖服务重建后已提交项目和任务仍可读取。"""
    stack = make_app_stack(tmp_path)
    project = stack.project_service.create_project(
        name="持久化项目", base_url="https://example.com"
    )
    task = stack.task_service.create_task(
        project_id=project.project_id,
        goal="服务重启后任务不丢失",
        start_url=project.base_url,
    )

    recreated = make_app_stack(tmp_path)

    assert recreated.project_service.get_project(project.project_id).name == "持久化项目"
    assert recreated.task_service.get_task(task.task_id).goal == "服务重启后任务不丢失"


@pytest.mark.integration
def test_cli_run_and_serve_commands_can_coexist():
    """覆盖 CLI 模式和 Web 模式命令入口并存。"""
    parser = cli_main.build_parser()

    serve_args = parser.parse_args(["serve", "--host", "127.0.0.1", "--port", "8000"])
    run_args = parser.parse_args(
        [
            "run",
            "--goal",
            "打开首页",
            "--url",
            "https://example.com",
            "--max-steps",
            "3",
        ]
    )

    assert serve_args.command == "serve"
    assert serve_args.host == "127.0.0.1"
    assert serve_args.port == 8000
    assert run_args.command == "run"
    assert run_args.goal == "打开首页"


async def _wait_for_task_status(
    service,
    task_id: str,
    status: TaskStatus,
    timeout_seconds: float = 2.0,
) -> Task:
    """等待任务进入指定状态。"""
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        task = service.get_task(task_id)
        if task.status is status:
            return task
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"任务未进入期望状态：{status.value}，当前：{task.status.value}")
        await asyncio.sleep(0.02)


async def _drain_event_types(subscription) -> list[str]:
    """读取当前订阅队列中已有事件类型。"""
    event_types: list[str] = []
    while not subscription.queue.empty():
        event = await subscription.queue.get()
        event_types.append(event.event_type)
        subscription.queue.task_done()
    return event_types
