"""Argus CLI 入口。"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import msvcrt
import sys
from pathlib import Path

from argus_py.blackbox import BlackboxRunner
from argus_py.browser import BrowserSession, PlaywrightClient
from argus_py.cli.messages import llm_field_label, llm_message
from argus_py.core.constants import (
    DEFAULT_BROWSER,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
    PROJECT_NAME,
    PROJECT_VERSION,
)
from argus_py.core.enums import TaskType
from argus_py.core.exceptions import TaskError
from argus_py.core.paths import SCREENSHOTS_DIR, resolve_project_path
from argus_py.config.llm_settings import DEFAULT_LLM_ENV_FILE, load_llm_settings
from argus_py.llm import LLMClient
from argus_py.llm.prompts import load_prompt
from argus_py.task.models import Task
from argus_py.task.runner import TaskRunner
from argus_py.task.service import TaskService

LLM_CONNECTION_CHECK_PROMPT = "llm_connection_check.md"
LLM_CONNECTION_CHECK_MAX_TOKENS = 4
LLM_CONNECTION_CHECK_TEMPERATURE = 0.0
DEFAULT_SIMPLE_TASK_STEPS = 6
DEFAULT_SIMPLE_TASK_TIMEOUT = 180
DEFAULT_NORMAL_TASK_STEPS = 12
DEFAULT_NORMAL_TASK_TIMEOUT = 300
DEFAULT_COMPLEX_TASK_STEPS = 20
DEFAULT_COMPLEX_TASK_TIMEOUT = 600
SUPPORTED_BROWSERS = ("chromium", "firefox", "webkit")

LLM_ENV_KEYS = [
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_MAX_TOKENS",
    "LLM_TEMPERATURE",
    "LLM_MAX_RETRIES",
]


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(
        prog="argus",
        description="AI Native Test Platform",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROJECT_NAME} {PROJECT_VERSION}",
    )

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="执行黑盒测试任务")
    run_parser.add_argument("--goal", required=True, help="自然语言测试目标")
    run_parser.add_argument("--url", required=True, help="起始 URL")
    run_parser.add_argument("--max-steps", type=_positive_int, help="最大动作步数；不传时系统自动分配")
    run_parser.add_argument("--timeout", type=_positive_int, help="任务超时时间，单位秒；不传时系统自动分配")
    run_parser.add_argument(
        "--browser",
        choices=SUPPORTED_BROWSERS,
        default=DEFAULT_BROWSER,
        help="浏览器类型：chromium/firefox/webkit",
    )
    run_parser.add_argument("--headed", action="store_true", help="显示浏览器窗口，默认 headless")
    run_parser.add_argument("--create-only", action="store_true", help="只创建任务，不执行黑盒闭环")
    run_parser.add_argument(
        "--no-screenshot",
        action="store_true",
        help="创建任务时关闭截图开关",
    )

    browser_parser = subparsers.add_parser("browser", help="浏览器封装调试命令")
    browser_subparsers = browser_parser.add_subparsers(dest="browser_command")

    check_parser = browser_subparsers.add_parser("check", help="打开页面、执行可选动作并截图")
    check_parser.add_argument("--url", required=True, help="要打开的 URL")
    check_parser.add_argument(
        "--browser",
        choices=SUPPORTED_BROWSERS,
        default=DEFAULT_BROWSER,
        help="浏览器类型：chromium/firefox/webkit",
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

    llm_parser = subparsers.add_parser("llm", help="大模型调用调试命令")
    llm_subparsers = llm_parser.add_subparsers(dest="llm_command")

    llm_check_parser = llm_subparsers.add_parser("check", help="使用固定低消耗 Prompt 检查大模型连接")
    llm_check_parser.add_argument("--model", help="临时覆盖模型名称")
    llm_check_parser.add_argument("--base-url", help="临时覆盖接口地址")
    llm_check_parser.add_argument("--timeout", type=float, default=45.0, help="本次调试最大等待秒数")

    config_parser = subparsers.add_parser("config", help="交互式配置命令")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    llm_config_parser = config_subparsers.add_parser("llm", help="交互式配置大模型 API")
    llm_config_parser.add_argument("--env-file", default=str(DEFAULT_LLM_ENV_FILE), help="写入的大模型配置文件路径，默认 config/llm.env")
    llm_config_parser.add_argument("--advanced", action="store_true", help="显示最大输出 Token 数、温度、重试次数等高级配置")
    return parser


def _positive_int(value: str) -> int:
    """解析正整数命令行参数。"""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是正整数。") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数。")
    return number


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


def _run_config_llm(args: argparse.Namespace) -> int:
    """交互式配置 LLM API。"""
    env_path = resolve_project_path(args.env_file)
    current = _read_env_values(env_path)

    print(llm_message("start"))
    print(llm_message("target", path=env_path.resolve()))

    updates: dict[str, str] = {}
    api_key = _prompt_secret(llm_field_label("LLM_API_KEY"), bool(current.get("LLM_API_KEY")))
    if api_key is not None:
        if not api_key:
            print(llm_message("api_key_required"), file=sys.stderr)
            return 1
        updates["LLM_API_KEY"] = api_key

    updates["LLM_BASE_URL"] = _prompt_text(
        llm_field_label("LLM_BASE_URL"),
        current.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
    )
    updates["LLM_MODEL"] = _prompt_text(
        llm_field_label("LLM_MODEL"),
        current.get("LLM_MODEL", DEFAULT_LLM_MODEL),
    )
    if args.advanced:
        updates["LLM_MAX_TOKENS"] = _prompt_text(
            llm_field_label("LLM_MAX_TOKENS"),
            current.get("LLM_MAX_TOKENS", str(DEFAULT_LLM_MAX_TOKENS)),
        )
        updates["LLM_TEMPERATURE"] = _prompt_text(
            llm_field_label("LLM_TEMPERATURE"),
            current.get("LLM_TEMPERATURE", str(DEFAULT_LLM_TEMPERATURE)),
        )
        updates["LLM_MAX_RETRIES"] = _prompt_text(
            llm_field_label("LLM_MAX_RETRIES"),
            current.get("LLM_MAX_RETRIES", str(DEFAULT_LLM_MAX_RETRIES)),
        )
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
        print(f"数值配置格式错误：{exc}", file=sys.stderr)
        return 1

    _write_env_values(env_path, updates)
    print(llm_message("saved"))
    print(llm_message("verify_hint"))
    print("argus llm check")
    return 0


async def _run_browser_check(args: argparse.Namespace) -> int:
    """运行 T002 浏览器封装调试命令。"""
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


async def _run_llm_check(args: argparse.Namespace) -> int:
    """运行 T003 LLM 调用调试命令。"""
    llm_settings = load_llm_settings()
    prompt = load_prompt(LLM_CONNECTION_CHECK_PROMPT).strip()

    client = LLMClient(
        api_key=llm_settings.api_key,
        base_url=args.base_url or llm_settings.base_url,
        model=args.model or llm_settings.model,
        max_tokens=LLM_CONNECTION_CHECK_MAX_TOKENS,
        temperature=LLM_CONNECTION_CHECK_TEMPERATURE,
        max_retries=0,
    )
    print(f"正在调用大模型接口，最多等待 {args.timeout:g} 秒...")
    try:
        response = await asyncio.wait_for(
            client.complete(
                prompt=prompt,
            ),
            timeout=args.timeout,
        )
    except TimeoutError:
        print(
            f"LLM 检查超时：超过 {args.timeout:g} 秒未完成。请检查接口地址、代理或网络连接；"
            "也可以用 --timeout 临时调大等待时间。",
            file=sys.stderr,
        )
        return 1

    print(f"模型：{response.model}")
    print(f"结束原因：{response.finish_reason}")
    print(f"Token：{response.usage.to_dict()}")
    print("响应内容：")
    print(response.content)
    return 0


async def _run_task(args: argparse.Namespace) -> int:
    """创建并执行黑盒任务。"""
    service = TaskService()
    max_steps, timeout_seconds = _resolve_run_limits(args.goal, args.url, args.max_steps, args.timeout)
    task = service.create_task(
        goal=args.goal,
        start_url=args.url,
        max_steps=max_steps,
        timeout_seconds=timeout_seconds,
        capture_screenshots=not args.no_screenshot,
    )
    print(f"已创建任务：{task.task_id}")
    print(f"执行限制：最大 {max_steps} 步，超时 {timeout_seconds} 秒")

    if args.create_only:
        print("任务已保存，未执行。")
        return 0

    def browser_session_factory(current_task: Task) -> BrowserSession:
        client = PlaywrightClient(headless=not args.headed, browser_type=args.browser)
        return BrowserSession(
            client=client,
            screenshot_dir=SCREENSHOTS_DIR / current_task.task_id,
        )

    blackbox_runner = BlackboxRunner(
        service=service,
        browser_session_factory=browser_session_factory,
    )
    runner = TaskRunner(
        service=service,
        handlers={TaskType.BLACKBOX: blackbox_runner.run},
    )

    print("开始执行黑盒任务...")
    try:
        result = await runner.run(task)
    except TaskError as exc:
        latest = _load_latest_task(service, task)
        _print_task_result(latest)
        print(f"任务执行失败：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        latest = service.cancel_task(task.task_id)
        _print_task_result(latest)
        print("任务已取消。", file=sys.stderr)
        return 130

    _print_task_result(result)
    return 0


def _resolve_run_limits(
    goal: str,
    url: str,
    max_steps: int | None,
    timeout_seconds: int | None,
) -> tuple[int, int]:
    """解析或自动分配任务执行限制。"""
    inferred_steps, inferred_timeout = _infer_run_limits(goal, url)
    return (
        max_steps if max_steps is not None else inferred_steps,
        timeout_seconds if timeout_seconds is not None else inferred_timeout,
    )


def _infer_run_limits(goal: str, url: str) -> tuple[int, int]:
    """根据任务描述保守推断步数和超时时间。"""
    text = f"{goal} {url}".lower()
    simple_keywords = ["打开", "访问", "截图", "确认页面", "检查页面", "可访问", "title"]
    complex_keywords = [
        "登录",
        "注册",
        "提交",
        "表单",
        "创建",
        "新增",
        "编辑",
        "删除",
        "订单",
        "多步骤",
        "流程",
        "搜索",
        "筛选",
        "上传",
    ]

    if any(keyword in text for keyword in complex_keywords):
        return DEFAULT_COMPLEX_TASK_STEPS, DEFAULT_COMPLEX_TASK_TIMEOUT
    if any(keyword in text for keyword in simple_keywords):
        return DEFAULT_SIMPLE_TASK_STEPS, DEFAULT_SIMPLE_TASK_TIMEOUT
    return DEFAULT_NORMAL_TASK_STEPS, DEFAULT_NORMAL_TASK_TIMEOUT


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


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        try:
            return asyncio.run(_run_task(args))
        except KeyboardInterrupt:
            print("任务已取消。", file=sys.stderr)
            return 130
        except Exception as exc:
            print(f"任务执行失败：{exc}", file=sys.stderr)
            return 1

    if args.command == "browser":
        if args.browser_command == "check":
            try:
                return asyncio.run(_run_browser_check(args))
            except Exception as exc:
                print(f"浏览器检查失败：{exc}", file=sys.stderr)
                return 1
        parser.print_help()
        return 0

    if args.command == "llm":
        if args.llm_command == "check":
            try:
                return asyncio.run(_run_llm_check(args))
            except KeyboardInterrupt:
                print("LLM 检查已取消。", file=sys.stderr)
                return 130
            except Exception as exc:
                print(f"LLM 检查失败：{exc}", file=sys.stderr)
                return 1
        parser.print_help()
        return 0

    if args.command == "config":
        if args.config_command == "llm":
            return _run_config_llm(args)
        parser.print_help()
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
