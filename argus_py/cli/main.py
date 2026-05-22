"""Argus CLI 入口。"""

from __future__ import annotations

import argparse
import sys

from argus_py.cli.commands import auth, browser, config, run, serve
from argus_py.cli.commands import llm as llm_cmd
from argus_py.cli.io import setup_cli_logging
from argus_py.core.constants import PROJECT_NAME, PROJECT_VERSION


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
        import asyncio

        try:
            return asyncio.run(run.run(args))
        except KeyboardInterrupt:
            from argus_py.cli.utils import print_cli_cancelled

            print_cli_cancelled("任务执行")
            return 130
        except Exception as exc:
            from argus_py.cli.utils import print_cli_error

            print_cli_error("任务执行失败", exc)
            return 1

    if args.command == "browser":
        import asyncio

        if args.browser_command == "check":
            try:
                return asyncio.run(browser.run_check(args))
            except Exception as exc:
                from argus_py.cli.utils import print_cli_error

                print_cli_error("浏览器检查失败", exc)
                return 1
        parser.print_help()
        return 0

    if args.command == "auth":
        import asyncio

        if args.auth_command == "save":
            try:
                return asyncio.run(auth.run_save(args))
            except KeyboardInterrupt:
                from argus_py.cli.utils import print_cli_cancelled

                print_cli_cancelled("登录态保存")
                return 130
            except Exception as exc:
                from argus_py.cli.utils import print_cli_error

                print_cli_error("登录态保存失败", exc)
                return 1
        if args.auth_command == "list":
            return auth.run_list()
        parser.print_help()
        return 0

    if args.command == "llm":
        import asyncio

        if args.llm_command == "check":
            try:
                return asyncio.run(llm_cmd.run_check(args))
            except KeyboardInterrupt:
                from argus_py.cli.utils import print_cli_cancelled

                print_cli_cancelled("LLM 检查")
                return 130
            except Exception as exc:
                from argus_py.cli.utils import print_cli_error

                print_cli_error("LLM 检查失败", exc)
                return 1
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
