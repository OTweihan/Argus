from __future__ import annotations

import argparse

import pytest

from argus_py.cli import main as cli_main
from argus_py.cli import utils as cli_utils
from argus_py.cli.commands import auth as auth_cmd
from argus_py.cli.commands import run as run_cmd
from argus_py.core.enums import TaskStatus
from argus_py.task.models import Task
from argus_py.task.strategy import TaskExecutionLimits, resolve_execution_limits


class FakeTaskService:
    last_instance = None

    def __init__(self) -> None:
        self.task: Task | None = None
        FakeTaskService.last_instance = self

    def create_task(self, **kwargs) -> Task:
        task = Task(
            goal=kwargs["goal"],
            start_url=kwargs["start_url"],
            max_steps=kwargs["max_steps"],
            timeout_seconds=kwargs["timeout_seconds"],
            capture_screenshots=kwargs["capture_screenshots"],
        )
        self.task = task
        return task

    def get_task(self, task_id: str) -> Task:
        assert self.task is not None
        return self.task

    def cancel_task(self, task_id: str) -> Task:
        assert self.task is not None
        self.task.status = TaskStatus.CANCELLED
        return self.task


class FakeTaskRunner:
    def __init__(self, service, handlers) -> None:
        self.service = service
        self.handlers = handlers

    async def run(self, task: Task) -> Task:
        task.status = TaskStatus.COMPLETED
        task.result_summary = "执行完成"
        task.report_path = "outputs/reports/fake/index.html"
        return task


class FakeBlackboxRunner:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    async def run(self, task: Task) -> Task:
        return task


@pytest.mark.parametrize(
    "args",
    [
        ["run", "--goal", "打开页面", "--url", "https://example.com", "--max-steps", "0"],
        ["run", "--goal", "打开页面", "--url", "https://example.com", "--timeout", "-1"],
        ["run", "--goal", "打开页面", "--url", "https://example.com", "--browser", "unknown"],
        ["browser", "check", "--url", "https://example.com", "--browser", "unknown"],
    ],
    ids=["max_steps_zero", "timeout_negative", "run_unknown_browser", "browser_unknown_browser"],
)
def test_parser_rejects_invalid_args(args: list[str]) -> None:
    parser = cli_main.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(args)


def test_run_parser_accepts_auth_state():
    parser = cli_main.build_parser()

    args = parser.parse_args(
        [
            "run",
            "--goal",
            "检查个人中心",
            "--url",
            "https://example.com/profile",
            "--auth-state",
            "default",
        ]
    )

    assert args.auth_state == "default"


def test_resolve_auth_state_path_uses_named_state(monkeypatch, tmp_path):
    browser_states_dir = tmp_path / "browser-states"
    monkeypatch.setattr(cli_utils, "BROWSER_STATES_DIR", browser_states_dir)
    # auth_cmd 模块也有自己的 BROWSER_STATES_DIR 引用
    monkeypatch.setattr(auth_cmd, "BROWSER_STATES_DIR", browser_states_dir)

    assert cli_utils.resolve_auth_state_path("default") == browser_states_dir / "default.json"
    assert (
        cli_utils.resolve_auth_state_path("example.com") == browser_states_dir / "example.com.json"
    )
    assert (
        cli_utils.resolve_auth_state_path("10.18.90.80-8580")
        == browser_states_dir / "10.18.90.80-8580.json"
    )
    assert cli_utils.resolve_auth_state_path("default.json") == browser_states_dir / "default.json"


def test_auth_save_parser_allows_domain_name_default():
    parser = cli_main.build_parser()

    args = parser.parse_args(["auth", "save", "--url", "https://example.com/login"])

    assert args.name is None
    assert cli_utils.auth_state_name_from_url(args.url) == "example.com"
    assert cli_utils.auth_state_name_from_url("http://localhost:8080/login") == "localhost-8080"


def test_read_auth_state_sites(tmp_path):
    state_file = tmp_path / "example.com.json"
    state_file.write_text(
        """
{
  "cookies": [{"domain": ".example.com"}],
  "origins": [{"origin": "https://app.example.com"}]
}
""".strip(),
        encoding="utf-8",
    )

    assert auth_cmd._read_auth_state_sites(state_file) == "app.example.com、example.com"


@pytest.mark.asyncio
async def test_run_task_create_only(monkeypatch, capsys):
    monkeypatch.setattr(run_cmd, "TaskService", FakeTaskService)
    args = argparse.Namespace(
        goal="打开页面",
        url="https://example.com",
        max_steps=None,
        timeout=None,
        no_screenshot=False,
        create_only=True,
        headed=False,
        browser="chromium",
    )

    exit_code = await run_cmd.run(args)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "已创建任务" in output
    assert "最大 6 步" in output
    assert "未执行" in output


@pytest.mark.asyncio
async def test_run_task_executes_runner(monkeypatch, capsys):
    monkeypatch.setattr(run_cmd, "TaskService", FakeTaskService)
    monkeypatch.setattr(run_cmd, "TaskRunner", FakeTaskRunner)
    monkeypatch.setattr(run_cmd, "BlackboxRunner", FakeBlackboxRunner)
    args = argparse.Namespace(
        goal="打开页面",
        url="https://example.com",
        max_steps=None,
        timeout=None,
        no_screenshot=False,
        create_only=False,
        headed=False,
        browser="chromium",
    )

    exit_code = await run_cmd.run(args)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "开始执行黑盒任务" in output
    assert "任务状态：completed" in output
    assert "HTML 报告：outputs/reports/fake/index.html" in output


@pytest.mark.parametrize(
    ("goal", "url", "max_steps", "timeout", "expected"),
    [
        ("打开页面", "https://example.com", 9, 120, TaskExecutionLimits(9, 120)),
        ("打开页面", "https://example.com", 9, None, TaskExecutionLimits(9, 180)),
        ("登录后提交订单表单", "https://example.com", None, None, TaskExecutionLimits(20, 600)),
    ],
    ids=["all_user", "partial_user", "inferred"],
)
def test_resolve_run_limits(
    goal: str, url: str, max_steps: int | None, timeout: int | None, expected: TaskExecutionLimits
) -> None:
    assert resolve_execution_limits(goal, url, max_steps, timeout) == expected


def test_main_run_handles_keyboard_interrupt(monkeypatch, capsys):
    async def fake_run(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(run_cmd, "run", fake_run)

    exit_code = cli_main.main(["run", "--goal", "打开页面", "--url", "https://example.com"])

    error_output = capsys.readouterr().err
    assert exit_code == 130
    assert "已取消：任务执行" in error_output


def test_main_run_handles_generic_error_with_unified_format(monkeypatch, capsys):
    async def fake_run(args):
        raise RuntimeError("boom")

    monkeypatch.setattr(run_cmd, "run", fake_run)

    exit_code = cli_main.main(["run", "--goal", "打开页面", "--url", "https://example.com"])

    error_output = capsys.readouterr().err
    assert exit_code == 1
    assert "错误：任务执行失败" in error_output
    assert "详情：boom" in error_output
