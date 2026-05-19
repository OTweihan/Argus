import pytest
from fastapi import HTTPException

from argus_py.api.dependencies import load_server_settings
from argus_py.api.routes import projects as project_routes
from argus_py.api.routes import tasks as task_routes
from argus_py.api.schemas import ProjectCreateRequest, TaskCreateRequest
from argus_py.api.schemas.config import ModelConfigUpdateRequest
from argus_py.config.model_storage import ModelConfigSQLiteStorage
from argus_py.config.service import ModelConfigService
from argus_py.core.exceptions import TaskError
from argus_py.infra.queue import TaskQueue
from argus_py.llm.providers import default_base_url
from argus_py.project.service import ProjectService
from argus_py.project.storage import ProjectSQLiteStorage
from argus_py.task.application import TaskApplicationService
from argus_py.task.service import TaskService
from argus_py.task.storage import TaskFileStorage, TaskSQLiteStorage


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
        provider="dashscope",
        model="qwen-plus",
        base_url=custom_url,
    )

    orig_default = default_base_url("dashscope")
    update_url = custom_url or orig_default
    updated = service.update_model_config(
        config.model_config_id,
        {"provider": "openai", "base_url": update_url},
    )

    assert updated.provider == "openai"
    if expected_url is not None:
        assert updated.base_url == expected_url
    else:
        assert updated.base_url == default_base_url("openai")


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

    response = await task_routes.cancel_task(
        task.task_id,
        app=TaskApplicationService(
            task_service=task_service,
            queue=queue,
            project_service=ProjectService(
                ProjectSQLiteStorage(tmp_path / "stop.db"),
                task_service=task_service,
            ),
            model_config_service=ModelConfigService(
                ModelConfigSQLiteStorage(tmp_path / "models.db")
            ),
        ),
    )

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
        app=TaskApplicationService(
            task_service=task_service,
            queue=TaskQueue(),
            project_service=project_service,
            model_config_service=ModelConfigService(
                ModelConfigSQLiteStorage(tmp_path / "models.db")
            ),
        ),
    )

    assert task.capture_screenshots is False


@pytest.mark.parametrize(
    "outside_reports",
    [True, False],
    ids=["outside_reports_dir", "under_reports_dir"],
)
def test_report_path_validation(tmp_path, monkeypatch, outside_reports):
    from argus_py.task import query as task_query

    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(task_query, "REPORTS_DIR", reports_dir)
    task_service = TaskService(TaskSQLiteStorage(tmp_path / "report_test.db"))
    task = task_service.create_task(goal="报告路径测试", start_url="https://example.com")

    if outside_reports:
        task.report_path = str(tmp_path / "index.html")
        with pytest.raises(TaskError, match="报告路径不在允许的报告目录下"):
            task_service.resolve_report_path(task)
    else:
        report_dir = reports_dir / task.task_id
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "index.html"
        report_path.write_text("<html></html>", encoding="utf-8")
        task.report_path = str(report_path)
        assert task_service.resolve_report_path(task) == report_path.resolve()


from argus_py.api.routes import events as event_routes


def test_list_task_events_returns_timeline(tmp_path):
    """GET /tasks/{id}/events 返回已持久化的时间线事件。"""
    task_service = TaskService(TaskSQLiteStorage(tmp_path / "events.db"))
    task = task_service.create_task(goal="事件测试", start_url="https://example.com")
    task_service.emit_timeline(task.task_id, "start", "task", summary="开始")
    task_service.emit_timeline(task.task_id, "complete", "task", summary="完成")

    result = event_routes.list_task_events(task.task_id, service=task_service)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["eventType"] == "start"
    assert result[1]["eventType"] == "complete"
    assert result[0]["taskId"] == task.task_id


def test_list_task_events_404_for_missing_task(tmp_path):
    """不存在的 task_id 返回 404。"""
    task_service = TaskService(TaskSQLiteStorage(tmp_path / "events404.db"))

    with pytest.raises(HTTPException) as exc_info:
        event_routes.list_task_events("no-such", service=task_service)
    assert exc_info.value.status_code == 404


def test_list_llm_traces_returns_records(tmp_path, monkeypatch):
    """读取 JSONL 追踪文件。"""
    task_service = TaskService(TaskSQLiteStorage(tmp_path / "llm.db"))
    task = task_service.create_task(goal="LLM追踪测试")

    from argus_py.task import query as task_query

    traces_dir = tmp_path / "traces"
    traces_dir.mkdir()
    monkeypatch.setattr(task_query, "OUTPUT_DIR", tmp_path)

    trace_file = traces_dir / f"{task.task_id}.jsonl"
    trace_file.write_text(
        '{"model":"qwen","latencyMs":1500}\n{"model":"gpt4","latencyMs":800}\n',
        encoding="utf-8",
    )

    result = event_routes.list_llm_traces(task.task_id, service=task_service)
    assert len(result) == 2
    assert result[0]["model"] == "qwen"
    assert result[1]["latencyMs"] == 800


def test_list_llm_traces_404_for_missing_task(tmp_path):
    """不存在的 task_id 返回 404。"""
    task_service = TaskService(TaskSQLiteStorage(tmp_path / "llm404.db"))

    with pytest.raises(HTTPException) as exc_info:
        event_routes.list_llm_traces("no-such", service=task_service)
    assert exc_info.value.status_code == 404


def test_list_llm_traces_empty_when_no_file(tmp_path):
    """无 JSONL 文件时返回空列表。"""
    task_service = TaskService(TaskSQLiteStorage(tmp_path / "llm_empty.db"))
    task = task_service.create_task(goal="无追踪")

    result = event_routes.list_llm_traces(task.task_id, service=task_service)
    assert result == []


def test_list_llm_traces_pagination_streaming(tmp_path, monkeypatch):
    """skip/limit 分页：仅返回窗口内记录，且能跳过非法行。"""
    task_service = TaskService(TaskSQLiteStorage(tmp_path / "llm_page.db"))
    task = task_service.create_task(goal="分页测试")

    from argus_py.task import query as task_query

    traces_dir = tmp_path / "traces"
    traces_dir.mkdir()
    monkeypatch.setattr(task_query, "OUTPUT_DIR", tmp_path)

    lines = [f'{{"model":"m{i}","latencyMs":{i}}}' for i in range(5)]
    # 故意插入一行损坏的 JSON，验证流式扫描会跳过而不是抛 500
    lines.insert(2, "{not-a-json")
    (traces_dir / f"{task.task_id}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = event_routes.list_llm_traces(task.task_id, skip=1, limit=2, service=task_service)
    # 损坏行被跳过后剩 5 条；skip=1, limit=2 应取第 2、3 条
    assert [r["model"] for r in result] == ["m1", "m2"]


def test_get_trace_detail_returns_matching_record(tmp_path, monkeypatch):
    """GET /tasks/{id}/llm-traces/{trace_id} 返回匹配的追踪记录。"""
    task_service = TaskService(TaskSQLiteStorage(tmp_path / "trace_detail.db"))
    task = task_service.create_task(goal="追踪详情")

    from argus_py.task import query as task_query

    traces_dir = tmp_path / "traces"
    traces_dir.mkdir()
    monkeypatch.setattr(task_query, "OUTPUT_DIR", tmp_path)

    trace_file = traces_dir / f"{task.task_id}.jsonl"
    trace_file.write_text(
        '{"trace_id":"trc-001","phase":"planner","event":"task.llm.succeeded","model":"qwen"}\n'
        '{"trace_id":"trc-002","phase":"evaluator","event":"task.llm.succeeded","model":"gpt4"}\n',
        encoding="utf-8",
    )

    result = event_routes.get_trace_detail(task.task_id, "trc-001", service=task_service)
    assert result["traceId"] == "trc-001"
    assert result["phase"] == "planner"

    with pytest.raises(HTTPException) as exc_info:
        event_routes.get_trace_detail(task.task_id, "no-such", service=task_service)
    assert exc_info.value.status_code == 404


def test_get_trace_detail_404_for_missing_task(tmp_path):
    """不存在的 task_id 返回 404。"""
    task_service = TaskService(TaskSQLiteStorage(tmp_path / "trace_404.db"))
    with pytest.raises(HTTPException) as exc_info:
        event_routes.get_trace_detail("no-such", "trc-001", service=task_service)
    assert exc_info.value.status_code == 404


def test_debug_bundle_contains_task_and_traces(tmp_path, monkeypatch):
    """调试包包含 task.json 和 traces。"""
    import io
    import zipfile

    task_service = TaskService(TaskSQLiteStorage(tmp_path / "debug.db"))
    task = task_service.create_task(goal="调试包测试")

    from argus_py.task import query as task_query

    traces_dir = tmp_path / "traces"
    traces_dir.mkdir()
    monkeypatch.setattr(task_query, "OUTPUT_DIR", tmp_path)

    (traces_dir / f"{task.task_id}.jsonl").write_text(
        '{"trace_id":"trc-001","phase":"planner"}\n', encoding="utf-8"
    )

    response = event_routes.download_debug_bundle(task.task_id, service=task_service)
    assert response.status_code == 200
    assert "application/zip" in response.media_type

    # FileResponse 暴露 path 属性，直接从临时文件读取
    assert hasattr(response, "path")
    with open(response.path, "rb") as f:
        body = f.read()
    zf = zipfile.ZipFile(io.BytesIO(body))
    names = zf.namelist()
    assert "task.json" in names
    assert "traces/llm.jsonl" in names


def test_debug_bundle_404_for_missing_task(tmp_path):
    """不存在的 task_id 返回 404。"""
    task_service = TaskService(TaskSQLiteStorage(tmp_path / "debug_404.db"))
    with pytest.raises(HTTPException) as exc_info:
        event_routes.download_debug_bundle("no-such", service=task_service)
    assert exc_info.value.status_code == 404
