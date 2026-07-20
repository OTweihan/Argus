"""创建并执行黑盒测试任务。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from argus_py.blackbox import BlackboxRunner
from argus_py.browser import BrowserSession
from argus_py.cli.io import cli_cancelled, cli_error, cli_info, cli_success, print_task_result
from argus_py.cli.utils import load_latest_task, resolve_auth_state_path
from argus_py.core.enums import TaskType
from argus_py.core.exceptions import TaskError
from argus_py.core.paths import SCREENSHOTS_DIR
from argus_py.execution.runner import TaskRunner
from argus_py.runtime.container import create_container, create_task_application_service
from argus_py.task.models import Task

if TYPE_CHECKING:
    from argus_py.cli._types import SubParserAdder


def build_parser(subparsers: "SubParserAdder") -> None:
    """添加 run 子命令解析器。"""
    from argus_py.cli.utils import positive_int

    parser = subparsers.add_parser("run", help="执行黑盒测试任务")
    parser.add_argument("--goal", required=True, help="自然语言测试目标")
    parser.add_argument("--url", required=True, help="起始 URL")
    parser.add_argument("--max-steps", type=positive_int, help="最大动作步数；不传时系统自动分配")
    parser.add_argument(
        "--timeout", type=positive_int, help="任务超时时间，单位秒；不传时系统自动分配"
    )
    parser.add_argument(
        "--browser",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
        help="浏览器类型",
    )
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口，默认 headless")
    parser.add_argument("--auth-state", help="复用已保存登录态")
    parser.add_argument("--create-only", action="store_true", help="只创建任务，不执行黑盒闭环")
    parser.add_argument("--no-screenshot", action="store_true", help="创建任务时关闭截图开关")
    parser.add_argument(
        "--planner-extension",
        help="planner Prompt 业务扩展片段文件路径（追加到内置 planner Prompt 末尾）",
    )
    parser.add_argument(
        "--evaluator-extension",
        help="evaluator Prompt 业务扩展片段文件路径（追加到内置 evaluator Prompt 末尾）",
    )
    parser.add_argument("--project", help="关联项目 ID（合并项目默认 baseUrl、步数、超时等）")


async def run(args: argparse.Namespace) -> int:
    """创建并执行黑盒任务。"""
    c = create_container()
    app = create_task_application_service(c)
    auth_state_arg = getattr(args, "auth_state", None)
    auth_state_path = resolve_auth_state_path(auth_state_arg) if auth_state_arg else None
    if auth_state_path is not None and not auth_state_path.exists():
        cli_error(
            "任务执行失败",
            f"登录态文件不存在：{auth_state_path}",
            "请先执行 argus auth save --name <名称> --url <登录页>，或检查 --auth-state 路径。",
        )
        return 1

    prompt_extensions = _resolve_prompt_extensions(args)
    if prompt_extensions is None:
        return 1

    params = app.resolve_create_params(
        goal=args.goal,
        start_url=args.url,
        task_type=TaskType.BLACKBOX,
        project_id=getattr(args, "project", None),
        max_steps=args.max_steps,
        timeout_seconds=args.timeout,
        capture_screenshots=not args.no_screenshot,
        parameters={"prompt_extensions": prompt_extensions} if prompt_extensions else None,
    )

    task = app.create_task(**params)
    cli_success(f"已创建任务：{task.task_id}")
    cli_info(f"执行限制：最大 {params['max_steps']} 步，超时 {params['timeout_seconds']} 秒")

    if args.create_only:
        cli_info("任务已保存，未执行。")
        return 0

    runner = _build_runner(c, args, auth_state_path)
    cli_info("开始执行黑盒任务...")
    try:
        result = await runner.run(task)
    except TaskError as exc:
        latest = load_latest_task(c.task_read_service, task)
        print_task_result(latest, show_steps=True)
        cli_error("任务执行失败", exc)
        return 1
    except KeyboardInterrupt:
        latest = c.lifecycle_service.cancel_task(task.task_id)
        print_task_result(latest, show_steps=True)
        cli_cancelled("任务执行")
        return 130
    finally:
        from argus_py.browser.singleton import stop_shared_client

        await stop_shared_client()

    print_task_result(result, show_steps=True)
    return 0


def _resolve_prompt_extensions(args: argparse.Namespace) -> dict[str, str] | None:
    """读取 planner/evaluator prompt 扩展文件，失败时打印错误并返回 None。"""
    try:
        return _read_prompt_extensions(
            planner_path=getattr(args, "planner_extension", None),
            evaluator_path=getattr(args, "evaluator_extension", None),
        )
    except FileNotFoundError as exc:
        cli_error(
            "任务执行失败",
            f"Prompt 扩展文件不存在：{exc}",
            "请检查 --planner-extension / --evaluator-extension 路径是否正确。",
        )
        return None
    except PromptExtensionDecodeError as exc:
        cli_error(
            "任务执行失败",
            f"无法以 UTF-8 读取 --{exc.role}-extension 指向的文件 {exc.path}：{exc.reason}",
            (
                "请把该文件改存为 UTF-8（不带 BOM）后重试：\n"
                "  - VSCode：右下角点击编码 → Save with Encoding → UTF-8\n"
                f"  - PowerShell：(Get-Content '{exc.path}') | Set-Content '{exc.path}' -Encoding utf8"
            ),
        )
        return None
    except PromptExtensionReadError as exc:
        cli_error(
            "任务执行失败",
            f"无法读取 --{exc.role}-extension 指向的文件 {exc.path}：{exc.cause}",
            "请确认该路径是普通文件、当前用户具备读取权限。",
        )
        return None


def _build_runner(
    c,
    args: argparse.Namespace,
    auth_state_path: Path | None,
) -> TaskRunner:
    """构建黑盒 TaskRunner，含 browser session factory。"""

    def browser_session_factory(current_task: Task) -> BrowserSession:
        from argus_py.browser.singleton import shared_client

        context_options = {"storage_state": str(auth_state_path)} if auth_state_path else None
        return BrowserSession(
            client=shared_client(headless=not args.headed, browser_type=args.browser),
            screenshot_dir=SCREENSHOTS_DIR / current_task.task_id,
            context_options=context_options,
            stop_browser=False,
        )

    model_config = c.model_config_service
    blackbox_runner = BlackboxRunner(
        lifecycle=c.lifecycle_service,
        reader=c.task_read_service,
        log_service=c.log_service,
        timeline_service=c.timeline_service,
        browser_session_factory=browser_session_factory,
        model_config_service=model_config,
    )
    return TaskRunner(
        lifecycle=c.lifecycle_service,
        reader=c.task_read_service,
        handlers={TaskType.BLACKBOX: blackbox_runner.run},
        model_config_service=model_config,
    )


class PromptExtensionDecodeError(Exception):
    """Prompt 扩展文件存在但不是合法 UTF-8。

    把底层 ``UnicodeDecodeError`` 翻译成带角色（planner / evaluator）和路径信息
    的领域异常，便于 CLI 层给出"换 UTF-8 重存"的明确指引。
    """

    def __init__(self, role: str, path: Path, cause: UnicodeDecodeError) -> None:
        super().__init__(f"无法以 UTF-8 解码 {path}：{cause.reason}")
        self.role = role
        self.path = path
        self.cause = cause
        self.reason = cause.reason


class PromptExtensionReadError(Exception):
    """Prompt 扩展文件读取失败（权限不足 / 是目录 / 磁盘 IO 错误等）。"""

    def __init__(self, role: str, path: Path, cause: OSError) -> None:
        super().__init__(f"无法读取 {path}：{cause}")
        self.role = role
        self.path = path
        self.cause = cause


def _read_prompt_extensions(planner_path: str | None, evaluator_path: str | None) -> dict[str, str]:
    """读取 planner / evaluator 的 Prompt 扩展文件并归集。

    除了原有的 ``FileNotFoundError``，还会把非 UTF-8 解码失败与其它 IO 错误分别
    翻译为 ``PromptExtensionDecodeError`` / ``PromptExtensionReadError``，避免
    ``UnicodeDecodeError`` 直接冒泡到 main 产生不可读的 traceback。
    """
    extensions: dict[str, str] = {}
    for role, raw_path in (("planner", planner_path), ("evaluator", evaluator_path)):
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.exists():
            raise FileNotFoundError(str(path))
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise PromptExtensionDecodeError(role, path, exc) from exc
        except OSError as exc:
            # FileNotFoundError 已被上面 path.exists() 拦截，此分支主要兜底
            # PermissionError / IsADirectoryError / 网络驱动器 IO 错误等。
            raise PromptExtensionReadError(role, path, exc) from exc
        content = content.strip()
        if content:
            extensions[role] = content
    return extensions
