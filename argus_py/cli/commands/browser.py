"""浏览器封装调试命令。"""

from __future__ import annotations

import argparse
import asyncio

from argus_py.browser import BrowserSession, PlaywrightClient
from argus_py.cli.utils import print_cli_error
from argus_py.core.paths import SCREENSHOTS_DIR, resolve_project_path


def build_parser(subparsers: argparse._SubParsersAction) -> None:  # noqa: SLF001
    """添加 browser 子命令解析器。"""
    from argus_py.cli.utils import positive_int

    browser_parser = subparsers.add_parser("browser", help="浏览器封装调试命令")
    browser_subparsers = browser_parser.add_subparsers(dest="browser_command")

    check_parser = browser_subparsers.add_parser("check", help="打开页面、执行可选动作并截图")
    check_parser.add_argument("--url", required=True, help="要打开的 URL")
    check_parser.add_argument(
        "--browser",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
        help="浏览器类型",
    )
    check_parser.add_argument("--headed", action="store_true", help="显示浏览器窗口，默认 headless")
    check_parser.add_argument(
        "--screenshot",
        default=str(SCREENSHOTS_DIR / "browser-check.png"),
        help="截图输出路径",
    )
    check_parser.add_argument("--click", help="可选：打开页面后点击指定选择器")
    check_parser.add_argument("--fill-selector", help="可选：要输入文本的选择器")
    check_parser.add_argument("--fill-text", default="", help="可选：输入文本")
    check_parser.add_argument("--wait-ms", type=int, default=0, help="动作后额外等待毫秒数")


async def run_check(args: argparse.Namespace) -> int:
    """运行浏览器检查调试命令。"""
    screenshot_path = resolve_project_path(args.screenshot)
    client = PlaywrightClient(headless=not args.headed, browser_type=args.browser)

    async with BrowserSession(client=client, screenshot_dir=screenshot_path.parent) as session:
        print(f"打开页面：{args.url}")
        nav_result = await session.goto(args.url)
        print(f"页面标题：{nav_result.get('title', '')}")
        print(f"当前 URL：{nav_result.get('url_after', '')}")

        if args.fill_selector:
            print(f"输入文本：{args.fill_selector}")
            await session.fill(args.fill_selector, args.fill_text)

        if args.click:
            print(f"点击元素：{args.click}")
            await session.click(args.click)

        if args.wait_ms > 0:
            print(f"额外等待：{args.wait_ms} ms")
            await session.require_actions().wait(args.wait_ms)

        shot = await session.screenshot(screenshot_path.name)
        snapshot = await session.snapshot()

    print(f"截图文件：{shot}")
    print(f"快照 URL：{snapshot.url}")
    print(f"快照标题：{snapshot.title}")
    print(f"可交互元素数量：{len(snapshot.interactive_elements)}")
    print(f"控制台消息数量：{len(snapshot.console_messages)}")
    return 0
