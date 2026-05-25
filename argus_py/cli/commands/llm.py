"""大模型调用调试命令。"""

from __future__ import annotations

import argparse
import asyncio

from argus_py.cli.io import cli_error, cli_info, cli_print
from argus_py.config.service import ModelConfigService
from argus_py.llm import LLMClient

LLM_CONNECTION_CHECK_PROMPT = "Reply only: ok"
LLM_CONNECTION_CHECK_MAX_TOKENS = 4
LLM_CONNECTION_CHECK_TEMPERATURE = 0.0


def build_parser(subparsers: argparse._SubParsersAction) -> None:  # noqa: SLF001
    """添加 llm 子命令解析器。"""
    llm_parser = subparsers.add_parser("llm", help="大模型调用调试命令")
    llm_subparsers = llm_parser.add_subparsers(dest="llm_command")

    check_parser = llm_subparsers.add_parser("check", help="使用固定低消耗 Prompt 检查大模型连接")
    check_parser.add_argument("--model", help="临时覆盖模型名称")
    check_parser.add_argument("--base-url", help="临时覆盖接口地址")
    check_parser.add_argument("--timeout", type=float, default=45.0, help="本次调试最大等待秒数")


async def run_check(args: argparse.Namespace) -> int:
    """运行 LLM 连接检查。"""
    service = ModelConfigService()
    config = service.get_default_model_config()
    if config is None:
        cli_error(
            "未配置模型",
            "请先执行 argus config llm 配置大模型。",
        )
        return 1

    client = LLMClient(
        api_key=config.api_key,
        base_url=args.base_url or config.base_url,
        model=args.model or config.model,
        max_tokens=LLM_CONNECTION_CHECK_MAX_TOKENS,
        temperature=LLM_CONNECTION_CHECK_TEMPERATURE,
        max_retries=0,
    )
    cli_info(f"正在调用大模型接口，最多等待 {args.timeout:g} 秒...")
    try:
        try:
            response = await asyncio.wait_for(
                client.complete(prompt=LLM_CONNECTION_CHECK_PROMPT), timeout=args.timeout
            )
        except TimeoutError:
            cli_error(
                "LLM 检查超时",
                f"超过 {args.timeout:g} 秒未完成。",
                "请检查接口地址、代理或网络连接；也可以用 --timeout 临时调大等待时间。",
            )
            return 1

        cli_print(f"模型：{client.model}")
        cli_print(f"结束原因：{response.finish_reason}")
        cli_print(f"Token：{response.usage.to_dict()}")
        cli_print("响应内容：")
        cli_print(response.content)
        return 0
    finally:
        await client.aclose()
