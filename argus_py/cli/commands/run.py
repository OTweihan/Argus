"""创建并执行黑盒测试任务。"""

from __future__ import annotations

import argparse

from argus_py.blackbox import BlackboxRunner
from argus_py.browser import BrowserSession, PlaywrightClient
from argus_py.cli.utils import print_cli_cancelled, print_cli_error, resolve_auth_state_path
from argus_py.core.enums import TaskType
from argus_py.core.exceptions import TaskError
from argus_py.core.paths import SCREENSHOTS_DIR
from argus_py.execution.runner import TaskRunner
from argus_py.task.models import Task
from argus_py.task.service import TaskService
from argus_py.task.strategy import resolve_execution_limits


def build_parser(subparsers: argparse._SubParsersAction) -> None:  # noqa: SLF001
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


async def run(args: argparse.Namespace) -> int:
    """创建并执行黑盒任务。"""
    service = TaskService()
    limits = resolve_execution_limits(args.goal, args.url, args.max_steps, args.timeout)
    auth_state_arg = getattr(args, "auth_state", None)
    auth_state_path = resolve_auth_state_path(auth_state_arg) if auth_state_arg else None
    if auth_state_path is not None and not auth_state_path.exists():
        print_cli_error(
            "任务执行失败",
            f"登录态文件不存在：{auth_state_path}",
            "请先执行 argus auth save --name <名称> --url <登录页>，或检查 --auth-state 路径。",
        )
        return 1

    task = service.create_task(
        goal=args.goal,
        start_url=args.url,
        max_steps=limits.max_steps,
        timeout_seconds=limits.timeout_seconds,
        capture_screenshots=not args.no_screenshot,
    )
    print(f"已创建任务：{task.task_id}")
    print(f"执行限制：最大 {limits.max_steps} 步，超时 {limits.timeout_seconds} 秒")

    if args.create_only:
        print("任务已保存，未执行。")
        return 0

    def browser_session_factory(current_task: Task) -> BrowserSession:
        context_options = {"storage_state": str(auth_state_path)} if auth_state_path else None
        client = PlaywrightClient(
            headless=not args.headed,
            browser_type=args.browser,
            context_options=context_options,
        )
        return BrowserSession(
            client=client,
            screenshot_dir=SCREENSHOTS_DIR / current_task.task_id,
        )

    blackbox_runner = BlackboxRunner(
        service=service, browser_session_factory=browser_session_factory
    )
    runner = TaskRunner(service=service, handlers={TaskType.BLACKBOX: blackbox_runner.run})

    print("开始执行黑盒任务...")
    try:
        result = await runner.run(task)
    except TaskError as exc:
        latest = _load_latest_task(service, task)
        _print_task_result(latest)
        print_cli_error("任务执行失败", exc)
        return 1
    except KeyboardInterrupt:
        latest = service.cancel_task(task.task_id)
        _print_task_result(latest)
        print_cli_cancelled("任务执行")
        return 130

    _print_task_result(result)
    return 0


def _load_latest_task(service: TaskService, task: Task) -> Task:
    """读取最新任务快照。"""
    try:
        return service.get_task(task.task_id)
    except TaskError:
        return task


def _print_task_result(task: Task) -> None:
    """输出任务执行结果。"""
    print(f"任务 ID：{task.task_id}")
    print(f"任务状态：{task.status.value}")
    print(f"执行步骤：{task.current_step}")
    print(f"问题数量：{len(task.findings)}")
    if task.result_summary:
        print(f"结果摘要：{task.result_summary}")
    if task.report_path:
        print(f"HTML 报告：{task.report_path}")
    if task.error_message:
        print(f"错误信息：{task.error_message}")
