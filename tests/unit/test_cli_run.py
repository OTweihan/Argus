from __future__ import annotations

import argparse
from unittest import mock

import pytest

from argus_py.cli import main as cli_main
from argus_py.cli import utils as cli_utils
from argus_py.cli.commands import auth as auth_cmd
from argus_py.cli.commands import run as run_cmd
from argus_py.core.enums import TaskStatus
from argus_py.runtime.container import RuntimeContainer
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


@pytest.fixture(autouse=True)
def _patch_container(monkeypatch) -> FakeTaskService:
    """把 CLI run() 中的 create_container 替换为返回 FakeTaskService 的容器。"""
    fake_service = FakeTaskService()
    container = mock.MagicMock(spec=RuntimeContainer)
    container.task_service = fake_service
    container.model_config_service = mock.MagicMock()
    container.task_queue = mock.MagicMock()
    container.project_service = mock.MagicMock()
    monkeypatch.setattr(run_cmd, "create_container", lambda: container)
    return fake_service


class FakeTaskRunner:
    def __init__(self, service, handlers, model_config_service=None) -> None:
        self.service = service
        self.handlers = handlers
        self._model_config_service = model_config_service

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


# ─── Prompt 扩展文件编码 / IO 错误友好提示 ──────────────────────────


def test_read_prompt_extensions_utf8_success(tmp_path):
    planner = tmp_path / "planner.md"
    planner.write_text("planner 扩展内容\n第二行", encoding="utf-8")
    evaluator = tmp_path / "evaluator.md"
    evaluator.write_text("evaluator 扩展", encoding="utf-8")

    out = run_cmd._read_prompt_extensions(str(planner), str(evaluator))

    assert out == {"planner": "planner 扩展内容\n第二行", "evaluator": "evaluator 扩展"}


def test_read_prompt_extensions_skips_empty_files(tmp_path):
    """空文件 / 仅空白 → 该角色不进入返回字典。"""
    planner = tmp_path / "planner.md"
    planner.write_text("   \n  \t", encoding="utf-8")

    out = run_cmd._read_prompt_extensions(str(planner), None)

    assert out == {}


def test_read_prompt_extensions_missing_file_raises_filenotfound(tmp_path):
    missing = tmp_path / "absent.md"
    with pytest.raises(FileNotFoundError) as exc_info:
        run_cmd._read_prompt_extensions(str(missing), None)
    assert str(missing) in str(exc_info.value)


def test_read_prompt_extensions_non_utf8_raises_decode_error(tmp_path):
    """GBK / Latin-1 等非 UTF-8 编码文件应翻译为 PromptExtensionDecodeError，
    并带上 role / path / reason 三个关键信息。"""
    bad = tmp_path / "planner_gbk.md"
    # 使用一个 UTF-8 严格无效的字节序列：0xFF 0xFE（UTF-16 BOM）+ 0x80
    bad.write_bytes(b"\xff\xfe planner \x80\xff content")

    with pytest.raises(run_cmd.PromptExtensionDecodeError) as exc_info:
        run_cmd._read_prompt_extensions(str(bad), None)

    err = exc_info.value
    assert err.role == "planner"
    assert err.path == bad
    # reason 由底层 UnicodeDecodeError 提供，应非空字符串
    assert isinstance(err.reason, str)
    assert err.reason


def test_read_prompt_extensions_directory_raises_read_error(tmp_path):
    """把目录路径传进来：path.exists() 返回 True、read_text 抛 IsADirectoryError
    （Linux）或 PermissionError（Windows），均应转为 PromptExtensionReadError。"""
    sub_dir = tmp_path / "evaluator_dir"
    sub_dir.mkdir()

    with pytest.raises(run_cmd.PromptExtensionReadError) as exc_info:
        run_cmd._read_prompt_extensions(None, str(sub_dir))

    err = exc_info.value
    assert err.role == "evaluator"
    assert err.path == sub_dir
    # 底层异常应是 OSError 子类
    assert isinstance(err.cause, OSError)


@pytest.mark.asyncio
async def test_run_translates_decode_error_to_friendly_message(monkeypatch, capsys, tmp_path):
    """端到端：CLI run() 收到非 UTF-8 扩展文件时应 return 1 +
    输出中文提示 + 给出转码命令建议，不能让 UnicodeDecodeError 冒泡。"""
    bad = tmp_path / "planner.md"
    bad.write_bytes(b"\xff\xfe non-utf8 \x80\xff")

    args = argparse.Namespace(
        goal="打开页面",
        url="https://example.com",
        max_steps=None,
        timeout=None,
        no_screenshot=False,
        create_only=True,
        headed=False,
        browser="chromium",
        planner_extension=str(bad),
        evaluator_extension=None,
    )

    exit_code = await run_cmd.run(args)
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "错误：任务执行失败" in captured.err
    # 路径与角色都应出现在 detail 行
    assert str(bad) in captured.err
    assert "--planner-extension" in captured.err
    # hint 应明确建议 UTF-8 转码
    assert "UTF-8" in captured.err


@pytest.mark.asyncio
async def test_run_translates_read_error_to_friendly_message(monkeypatch, capsys, tmp_path):
    """非编码的 IO 错误（这里用目录路径触发）也应得到友好中文提示。"""
    sub_dir = tmp_path / "evaluator_dir"
    sub_dir.mkdir()

    args = argparse.Namespace(
        goal="打开页面",
        url="https://example.com",
        max_steps=None,
        timeout=None,
        no_screenshot=False,
        create_only=True,
        headed=False,
        browser="chromium",
        planner_extension=None,
        evaluator_extension=str(sub_dir),
    )

    exit_code = await run_cmd.run(args)
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "错误：任务执行失败" in captured.err
    assert str(sub_dir) in captured.err
    assert "--evaluator-extension" in captured.err
