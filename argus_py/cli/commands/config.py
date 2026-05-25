"""交互式配置命令 — 写入 SQLite 模型配置。"""

from __future__ import annotations

import argparse
import getpass
import sys

from argus_py.cli.io import cli_error, cli_info, cli_print
from argus_py.cli.messages import llm_field_label, llm_message
from argus_py.config.service import ModelConfigService
from argus_py.core.constants import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MAX_RETRIES, DEFAULT_LLM_MODEL
from argus_py.core.exceptions import ModelConfigError
from argus_py.core.ids import generate_model_config_id


def build_parser(subparsers: argparse._SubParsersAction) -> None:  # noqa: SLF001
    """添加 config 子命令解析器。"""
    config_parser = subparsers.add_parser("config", help="交互式配置命令")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    llm_parser = config_subparsers.add_parser("llm", help="交互式配置大模型 API")
    llm_parser.add_argument("--advanced", action="store_true", help="显示重试次数等高级参数")


def run_llm(args: argparse.Namespace) -> int:
    """交互式配置 LLM API — 写入 SQLite。"""
    service = ModelConfigService()

    existing = service.get_default_model_config()
    if existing:
        cli_info(f"将更新默认模型配置「{existing.name}」（{existing.model}）")
    else:
        cli_info(llm_message("start"))
        cli_info("配置将保存到数据库，可通过 Web 控制台或 argus config llm 管理。")

    api_key = _prompt_secret(llm_field_label("LLM_API_KEY"), bool(existing and existing.api_key))
    if api_key is not None:
        if not api_key:
            cli_error(
                "大模型配置失败",
                llm_message("api_key_required"),
                "请重新执行 argus config llm 并输入 API Key。",
            )
            return 1
    elif existing:
        api_key = existing.api_key

    base_url = _prompt_text(
        llm_field_label("LLM_BASE_URL"),
        existing.base_url if existing else DEFAULT_LLM_BASE_URL,
    )
    model = _prompt_text(
        llm_field_label("LLM_MODEL"),
        existing.model if existing else DEFAULT_LLM_MODEL,
    )

    if args.advanced:
        max_retries_str = _prompt_text(
            llm_field_label("LLM_MAX_RETRIES"),
            str(existing.max_retries) if existing else str(DEFAULT_LLM_MAX_RETRIES),
        )
    else:
        max_retries_str = str(existing.max_retries if existing else DEFAULT_LLM_MAX_RETRIES)
        cli_info(llm_message("advanced_default"))

    try:
        max_retries = int(max_retries_str)
    except ValueError as exc:
        cli_error(
            "大模型配置失败",
            f"数值配置格式错误：{exc}",
            "请检查最大重试次数。",
        )
        return 1

    if not isinstance(api_key, str):
        api_key = ""

    try:
        if existing:
            service.update_model_config(
                existing.model_config_id,
                {
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model,
                    "max_retries": max_retries,
                    "timeout_seconds": existing.timeout_seconds,
                },
            )
            cli_info(f"默认模型配置「{existing.name}」已更新。")
        else:
            name = f"default-{generate_model_config_id()[:8]}"
            service.create_model_config(
                name=name,
                api_key=api_key,
                base_url=base_url,
                model=model,
                max_retries=max_retries,
                timeout_seconds=120.0,
                is_default=True,
            )
            cli_info("默认模型配置已创建。")
    except ModelConfigError as exc:
        cli_error("大模型配置失败", str(exc))
        return 1

    cli_info(llm_message("verify_hint"))
    cli_print("argus llm check")
    return 0


def _prompt_secret(label: str, has_existing: bool) -> str | None:
    """读取敏感配置输入，回车保留已有值。"""
    suffix = f" [{llm_message('keep_existing')}]" if has_existing else ""
    try:
        value = _read_masked_input(f"{label}{suffix}: ").strip()
    except (AttributeError, OSError):
        value = getpass.getpass(f"{label}{suffix}: ").strip()
    if not value and has_existing:
        return None
    return value


def _prompt_text(label: str, default: str) -> str:
    """读取普通配置输入，回车使用默认值。"""
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _read_masked_input(prompt: str, mask: str = "*") -> str:
    """读取敏感输入，并用掩码字符显示输入进度。"""
    try:
        import msvcrt  # Windows-only
    except ImportError:
        return getpass.getpass(prompt)

    if not sys.stdin.isatty():
        return getpass.getpass(prompt)

    sys.stdout.write(prompt)
    sys.stdout.flush()
    chars: list[str] = []

    while True:
        char = msvcrt.getwch()  # type: ignore[attr-defined]
        if char in {"\r", "\n"}:
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(chars)
        if char == "\x03":
            raise KeyboardInterrupt
        if char in {"\b", "\x7f"}:
            if chars:
                chars.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue
        if char in {"\x00", "\xe0"}:
            msvcrt.getwch()  # type: ignore[attr-defined]
            continue
        chars.append(char)
        sys.stdout.write(mask)
        sys.stdout.flush()
