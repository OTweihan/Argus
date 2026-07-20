"""Argus CLI 入口。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Coroutine
from typing import Any

from argus_py.cli._types import SubParserAdder  # noqa: F401
from argus_py.cli.commands import analyze, auth, browser, config, run, serve
from argus_py.cli.commands import llm as llm_cmd
from argus_py.cli.io import setup_cli_logging
from argus_py.cli.utils import print_cli_cancelled, print_cli_error
from argus_py.core.constants import PROJECT_NAME, PROJECT_VERSION


def _run_async_command(coro: Coroutine[Any, Any, int], label: str) -> int:
    """统一异步子命令执行：asyncio.run + 统一异常处理。"""
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        print_cli_cancelled(label)
        return 130
    except Exception as exc:
        print_cli_error(f"{label}失败", exc)
        return 1


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(prog="argus", description="AI Native Test Platform")
    parser.add_argument("--version", action="version", version=f"{PROJECT_NAME} {PROJECT_VERSION}")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="提升 CLI 日志级别（-v=INFO，-vv=DEBUG）；默认仅显示 WARNING 及以上",
    )

    subparsers = parser.add_subparsers(dest="command")
    serve.build_parser(subparsers)
    run.build_parser(subparsers)
    analyze.build_parser(subparsers)
    browser.build_parser(subparsers)
    auth.build_parser(subparsers)
    llm_cmd.build_parser(subparsers)
    config.build_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    # serve 命令由 FastAPI lifespan 调用 setup_logging 加载完整 YAML 配置；
    # 其它一次性命令使用精简 console 配置，避免和 server 进程争抢日志文件。
    if args.command != "serve":
        setup_cli_logging(verbose=getattr(args, "verbose", 0))

    if args.command == "serve":
        return serve.run(args)

    if args.command == "run":
        return _run_async_command(run.run(args), "任务执行")

    if args.command == "analyze":
        return _run_async_command(analyze.run(args), "白盒分析")

    if args.command == "browser":
        if args.browser_command == "check":
            return _run_async_command(browser.run_check(args), "浏览器检查")
        parser.print_help()
        return 0

    if args.command == "auth":
        if args.auth_command == "save":
            return _run_async_command(auth.run_save(args), "登录态保存")
        if args.auth_command == "list":
            return auth.run_list()
        parser.print_help()
        return 0

    if args.command == "llm":
        if args.llm_command == "check":
            return _run_async_command(llm_cmd.run_check(args), "LLM 检查")
        parser.print_help()
        return 0

    if args.command == "config":
        if args.config_command == "llm":
            return config.run_llm(args)
        parser.print_help()
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
