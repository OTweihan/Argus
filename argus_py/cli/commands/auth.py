"""浏览器登录态管理命令。"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from argus_py.browser import BrowserSession, PlaywrightClient
from argus_py.cli.utils import print_cli_error, print_cli_cancelled, resolve_auth_state_path, auth_state_name_from_url
from argus_py.core.paths import BROWSER_STATES_DIR


def build_parser(subparsers: argparse._SubParsersAction) -> None:  # noqa: SLF001
    """添加 auth 子命令解析器。"""
    auth_parser = subparsers.add_parser("auth", help="浏览器登录态管理命令")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command")

    save_parser = auth_subparsers.add_parser("save", help="打开登录页并保存浏览器登录态")
    save_parser.add_argument("--name", help="登录态名称；不传时默认使用 URL 域名")
    save_parser.add_argument("--url", required=True, help="需要手动登录的页面 URL")
    save_parser.add_argument("--browser", choices=("chromium", "firefox", "webkit"), default="chromium", help="浏览器类型")
    save_parser.add_argument("--headed", action="store_true", help="显示浏览器窗口；auth save 默认显示")
    save_parser.add_argument("--headless", action="store_true", help="不显示浏览器窗口")

    auth_subparsers.add_parser("list", help="列出已保存的浏览器登录态")


async def run_save(args: argparse.Namespace) -> int:
    """打开登录页面，等待用户登录后保存 storage_state。"""
    if args.headed and args.headless:
        print_cli_error("登录态保存失败", "--headed 和 --headless 不能同时使用。")
        return 1

    auth_state_name = args.name or auth_state_name_from_url(args.url)
    auth_state_path = resolve_auth_state_path(auth_state_name)
    auth_state_path.parent.mkdir(parents=True, exist_ok=True)

    if auth_state_path.exists():
        print(f"将覆盖已有登录态：{auth_state_path}")

    client = PlaywrightClient(headless=args.headless, browser_type=args.browser)
    async with BrowserSession(client=client) as session:
        print(f"打开登录页面：{args.url}")
        await session.goto(args.url)
        print("请在浏览器中完成登录。")
        try:
            await asyncio.to_thread(input, "登录完成后回到终端，按 Enter 保存登录态：")
        except EOFError:
            print_cli_error("登录态保存失败", "当前终端无法读取确认输入。")
            return 1
        if session.context is None:
            print_cli_error("登录态保存失败", "浏览器上下文未创建。")
            return 1
        await session.context.storage_state(path=str(auth_state_path))

    print(f"登录态已保存：{auth_state_path}")
    print(f"登录态名称：{auth_state_name}")
    print(f"运行任务时可使用：argus run --auth-state {auth_state_name} --goal \"...\" --url \"...\"")
    return 0


def run_list() -> int:
    """列出已保存的浏览器登录态文件。"""
    if not BROWSER_STATES_DIR.exists():
        print("暂无已保存登录态。")
        return 0

    state_files = sorted(BROWSER_STATES_DIR.glob("*.json"))
    if not state_files:
        print("暂无已保存登录态。")
        return 0

    print("已保存登录态：")
    for state_file in state_files:
        print(f"- 名称：{state_file.stem}")
        print(f"  关联站点：{_read_auth_state_sites(state_file)}")
        print(f"  修改时间：{_format_local_timestamp(state_file.stat().st_mtime)}")
        print(f"  复用命令：argus run --auth-state {state_file.stem} --goal \"...\" --url \"...\"")
        print(f"  文件路径：{state_file}")
    return 0


def _format_local_timestamp(timestamp: float) -> str:
    """格式化本地时间，精确到秒。"""
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%dT%H:%M:%S")


def _read_auth_state_sites(path: Path) -> str:
    """从 Playwright storage_state 中提取可读站点信息。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "无法读取"

    sites: set[str] = set()
    for cookie in data.get("cookies", []):
        domain = str(cookie.get("domain", "")).lstrip(".")
        if domain:
            sites.add(domain)
    for origin in data.get("origins", []):
        parsed = urlparse(str(origin.get("origin", "")))
        if parsed.netloc:
            sites.add(parsed.netloc)

    if not sites:
        return "未记录站点"
    return "、".join(sorted(sites))
