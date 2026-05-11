import pytest
from fastapi import HTTPException

from argus_py.api.dependencies import load_server_settings
from argus_py.api.routes import projects as project_routes
from argus_py.api.routes import reports as report_routes
from argus_py.api.routes import tasks as task_routes
from argus_py.api.schemas import ProjectCreateRequest, TaskCreateRequest
from argus_py.api.schemas.config import ModelConfigUpdateRequest
from argus_py.config.model_storage import ModelConfigSQLiteStorage
from argus_py.config.models import ModelProvider
from argus_py.config.service import ModelConfigService
from argus_py.infra.queue import TaskQueue
from argus_py.llm.providers import default_base_url
from argus_py.project.service import ProjectService
from argus_py.project.storage import ProjectSQLiteStorage
from argus_py.task.models import Task
from argus_py.task.service import TaskService
from argus_py.task.storage import TaskFileStorage


@pytest.mark.parametrize(
    ("custom_url", "expected_url"),
    [
        pytest.param(None, None, id="reset_to_provider_default"),
        pytest.param(
            "https://llm.example.test/v1", "https://llm.example.test/v1", id="keep_custom"
        ),
    ],
)
def test_model_provider_change_base_url(tmp_path, custom_url, expected_url):
    service = ModelConfigService(ModelConfigSQLiteStorage(tmp_path / "argus.db"))
    config = service.create_model_config(
        name="测试模型",
        provider=ModelProvider.DASHSCOPE,
        model="qwen-plus",
        base_url=custom_url,
    )

    orig_default = default_base_url(ModelProvider.DASHSCOPE)
    update_url = custom_url or orig_default
    updated = service.update_model_config(
        config.model_config_id,
        {"provider": ModelProvider.OPENAI, "base_url": update_url},
    )

    assert updated.provider is ModelProvider.OPENAI
    if expected_url is not None:
        assert updated.base_url == expected_url
    else:
        assert updated.base_url == default_base_url(ModelProvider.OPENAI)


def test_server_settings_normalize_string_values(tmp_path):
    config_path = tmp_path / "server.yaml"
    config_path.write_text(
        """
server:
  port: "9000"
  reload: "false"
cors:
  allow_origins: "http://localhost:5173, http://127.0.0.1:5173"
  allow_credentials: "false"
  allow_methods: "*"
scheduler:
  concurrency: "2"
  queue_max_size: "bad"
events:
  history_limit: "-1"
  subscriber_queue_size: "0"
""".strip(),
        encoding="utf-8",
    )

    settings = load_server_settings(str(config_path))

    assert settings.port == 9000
    assert settings.reload is False
    assert settings.cors_allow_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert settings.cors_allow_credentials is False
    assert settings.cors_allow_methods == ["*"]
    assert settings.scheduler_concurrency == 2
    assert settings.scheduler_queue_max_size == 0
    assert settings.events_history_limit == 0
    assert settings.events_subscriber_queue_size == 1


def test_api_requests_normalize_blank_text_fields():
    project = ProjectCreateRequest(
        name="  演示项目  ",
        base_url="   ",
        git_url=" https://git.example.test/repo.git ",
    )
    task = TaskCreateRequest(
        goal="  打开首页  ",
        project_id=" project-demo ",
        start_url=" ",
        model_config_id=" ",
    )
    model_update = ModelConfigUpdateRequest(task_type="")

    assert project.name == "演示项目"
    assert project.base_url is None
    assert project.git_url == "https://git.example.test/repo.git"
    assert task.goal == "打开首页"
    assert task.project_id == "project-demo"
    assert task.start_url is None
    assert task.model_config_id is None
    assert model_update.task_type is None


@pytest.mark.asyncio
async def test_task_queue_cancel_clears_scheduler_status():
    queue = TaskQueue()

    await queue.enqueue("task-queued")

    assert await queue.scheduler_status("task-queued") == "queued"
    assert await queue.cancel("task-queued") is True
    assert await queue.scheduler_status("task-queued") is None
    await queue.request_stop(1)
    assert await queue.get() is None
    await queue.complete(None)


@pytest.mark.asyncio
async def test_stop_queued_task_clears_scheduler_status(tmp_path):
    task_service = TaskService(TaskFileStorage(tmp_path / "tasks"))
    queue = TaskQueue()
    task = task_service.create_task(goal="等待执行", start_url="https://example.com")
    await queue.enqueue(task.task_id)

    response = await task_routes.stop_task(task.task_id, service=task_service, queue=queue)

    assert response.status.value == "cancelled"
    assert response.scheduler_status is None
    assert await queue.scheduler_status(task.task_id) is None


@pytest.mark.asyncio
async def test_web_task_creation_inherits_project_screenshot_default(tmp_path):
    task_service = TaskService(TaskFileStorage(tmp_path / "tasks"))
    project_service = ProjectService(
        ProjectSQLiteStorage(tmp_path / "argus.db"),
        task_service=task_service,
    )
    project = await project_routes.create_project(
        ProjectCreateRequest(
            name="项目默认值",
            base_url="https://example.com",
            default_capture_screenshots=False,
        ),
        service=project_service,
    )

    task = await task_routes.create_task(
        TaskCreateRequest(
            project_id=project.project_id,
            goal="继承项目默认截图配置",
            capture_screenshots=None,
        ),
        service=task_service,
        project_service=project_service,
        model_config_service=ModelConfigService(ModelConfigSQLiteStorage(tmp_path / "models.db")),
    )

    assert task.capture_screenshots is False


@pytest.mark.parametrize(
    "outside_reports",
    [True, False],
    ids=["outside_reports_dir", "under_reports_dir"],
)
def test_report_path_validation(tmp_path, monkeypatch, outside_reports):
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(report_routes, "REPORTS_DIR", reports_dir)
    task = Task(goal="报告路径测试")

    if outside_reports:
        task.report_path = str(tmp_path / "index.html")
        with pytest.raises(HTTPException) as exc_info:
            report_routes._resolve_html_report_path(task)
        assert exc_info.value.status_code == 404
    else:
        report_dir = reports_dir / task.task_id
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "index.html"
        report_path.write_text("<html></html>", encoding="utf-8")
        task.report_path = str(report_path)
        assert report_routes._resolve_html_report_path(task) == report_path.resolve()
