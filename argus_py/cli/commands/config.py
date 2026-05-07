"""交互式配置命令。"""

from __future__ import annotations

import argparse
import getpass
import msvcrt
import sys
from pathlib import Path

from argus_py.cli.messages import llm_field_label, llm_message
from argus_py.cli.utils import print_cli_error
from argus_py.core.constants import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MAX_RETRIES, DEFAULT_LLM_MAX_TOKENS, DEFAULT_LLM_MODEL, DEFAULT_LLM_TEMPERATURE
from argus_py.core.crypto import encrypt_api_key
from argus_py.core.paths import resolve_project_path

LLM_ENV_KEYS = [
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_MAX_TOKENS",
    "LLM_TEMPERATURE",
    "LLM_MAX_RETRIES",
]


def build_parser(subparsers: argparse._SubParsersAction) -> None:  # noqa: SLF001
    """添加 config 子命令解析器。"""
    from argus_py.config.llm_settings import DEFAULT_LLM_ENV_FILE

    config_parser = subparsers.add_parser("config", help="交互式配置命令")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    llm_parser = config_subparsers.add_parser("llm", help="交互式配置大模型 API")
    llm_parser.add_argument("--env-file", default=str(DEFAULT_LLM_ENV_FILE), help="写入的大模型配置文件路径，默认 config/llm.env")
    llm_parser.add_argument("--advanced", action="store_true", help="显示最大输出 Token 数、温度、重试次数等高级配置")


def run_llm(args: argparse.Namespace) -> int:
    """交互式配置 LLM API。"""
    env_path = resolve_project_path(args.env_file)
    current = _read_env_values(env_path)

    print(llm_message("start"))
    print(llm_message("target", path=env_path.resolve()))

    updates: dict[str, str] = {}
    api_key = _prompt_secret(llm_field_label("LLM_API_KEY"), bool(current.get("LLM_API_KEY")))
    if api_key is not None:
        if not api_key:
            print_cli_error(
                "大模型配置失败",
                llm_message("api_key_required"),
                "请重新执行 argus config llm 并输入 API Key。",
            )
            return 1
        updates["LLM_API_KEY"] = encrypt_api_key(api_key)

    updates["LLM_BASE_URL"] = _prompt_text(llm_field_label("LLM_BASE_URL"), current.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL))
    updates["LLM_MODEL"] = _prompt_text(llm_field_label("LLM_MODEL"), current.get("LLM_MODEL", DEFAULT_LLM_MODEL))
    if args.advanced:
        updates["LLM_MAX_TOKENS"] = _prompt_text(llm_field_label("LLM_MAX_TOKENS"), current.get("LLM_MAX_TOKENS", str(DEFAULT_LLM_MAX_TOKENS)))
        updates["LLM_TEMPERATURE"] = _prompt_text(llm_field_label("LLM_TEMPERATURE"), current.get("LLM_TEMPERATURE", str(DEFAULT_LLM_TEMPERATURE)))
        updates["LLM_MAX_RETRIES"] = _prompt_text(llm_field_label("LLM_MAX_RETRIES"), current.get("LLM_MAX_RETRIES", str(DEFAULT_LLM_MAX_RETRIES)))
    else:
        updates["LLM_MAX_TOKENS"] = current.get("LLM_MAX_TOKENS", str(DEFAULT_LLM_MAX_TOKENS))
        updates["LLM_TEMPERATURE"] = current.get("LLM_TEMPERATURE", str(DEFAULT_LLM_TEMPERATURE))
        updates["LLM_MAX_RETRIES"] = current.get("LLM_MAX_RETRIES", str(DEFAULT_LLM_MAX_RETRIES))
        print(llm_message("advanced_default"))

    try:
        int(updates["LLM_MAX_TOKENS"])
        float(updates["LLM_TEMPERATURE"])
        int(updates["LLM_MAX_RETRIES"])
    except ValueError as exc:
        print_cli_error("大模型配置失败", f"数值配置格式错误：{exc}", "请检查最大输出 Token 数、温度和最大重试次数。")
        return 1

    _write_env_values(env_path, updates)
    print(llm_message("saved"))
    print(llm_message("verify_hint"))
    print("argus llm check")
    return 0


def _read_env_values(path: Path) -> dict[str, str]:
    """读取 env 文件中的 key/value，不输出任何值。"""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _write_env_values(path: Path, updates: dict[str, str]) -> None:
    """写入 env 文件，保留已有未知配置和注释。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    written: set[str] = set()
    output: list[str] = []

    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            output.append(line)
            continue
        key, _ = line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key in updates:
            output.append(f"{normalized_key}={updates[normalized_key]}")
            written.add(normalized_key)
        else:
            output.append(line)

    if output and output[-1].strip():
        output.append("")

    for key in LLM_ENV_KEYS:
        if key in updates and key not in written:
            output.append(f"{key}={updates[key]}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _prompt_text(label: str, default: str) -> str:
    """读取普通配置输入，回车使用默认值。"""
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _read_masked_input(prompt: str, mask: str = "*") -> str:
    """读取敏感输入，并用掩码字符显示输入进度。"""
    if not sys.stdin.isatty():
        return getpass.getpass(prompt)

    sys.stdout.write(prompt)
    sys.stdout.flush()
    chars: list[str] = []

    while True:
        char = msvcrt.getwch()
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
            msvcrt.getwch()
            continue
        chars.append(char)
        sys.stdout.write(mask)
        sys.stdout.flush()


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
