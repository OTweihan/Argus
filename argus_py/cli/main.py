"""Argus CLI 入口。"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import msvcrt
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

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
from argus_py.core.paths import BROWSER_STATES_DIR, SCREENSHOTS_DIR, resolve_project_path
from argus_py.config.llm_settings import DEFAULT_LLM_ENV_FILE, load_llm_settings
from argus_py.llm import LLMClient
from argus_py.llm.prompts import load_prompt
from argus_py.task.models import Task
from argus_py.task.runner import TaskRunner
from argus_py.task.service import TaskService
from argus_py.task.strategy import resolve_execution_limits

LLM_CONNECTION_CHECK_PROMPT = "llm_connection_check.md"
LLM_CONNECTION_CHECK_MAX_TOKENS = 4
LLM_CONNECTION_CHECK_TEMPERATURE = 0.0
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

    serve_parser = subparsers.add_parser("serve", help="启动 FastAPI Web 服务")
    serve_parser.add_argument("--host", help="监听地址；不传时读取 config/server.yaml")
    serve_parser.add_argument("--port", type=_positive_int, help="监听端口；不传时读取 config/server.yaml")
    serve_parser.add_argument("--reload", action="store_true", default=None, help="启用开发热重载")
    serve_parser.add_argument(
        "--config",
        default="config/server.yaml",
        help="服务配置文件路径",
    )

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
    run_parser.add_argument(
        "--auth-state",
        help="复用已保存登录态；可传名称，例如 example.com，也可传 storage_state JSON 路径",
    )
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

    auth_parser = subparsers.add_parser("auth", help="浏览器登录态管理命令")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command")

    auth_save_parser = auth_subparsers.add_parser("save", help="打开登录页并保存浏览器登录态")
    auth_save_parser.add_argument("--name", help="登录态名称；不传时默认使用 URL 域名")
    auth_save_parser.add_argument("--url", required=True, help="需要手动登录的页面 URL")
    auth_save_parser.add_argument(
        "--browser",
        choices=SUPPORTED_BROWSERS,
        default=DEFAULT_BROWSER,
        help="浏览器类型：chromium/firefox/webkit",
    )
    auth_save_parser.add_argument("--headed", action="store_true", help="显示浏览器窗口；auth save 默认显示")
    auth_save_parser.add_argument("--headless", action="store_true", help="不显示浏览器窗口，通常不建议用于手动登录")

    auth_subparsers.add_parser("list", help="列出已保存的浏览器登录态")

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


def _print_cli_error(context: str, detail: object | None = None, hint: str | None = None) -> None:
    """统一输出 CLI 错误信息。"""
    print(f"错误：{context}", file=sys.stderr)
    if detail:
        print(f"详情：{detail}", file=sys.stderr)
    if hint:
        print(f"提示：{hint}", file=sys.stderr)


def _print_cli_cancelled(context: str) -> None:
    """统一输出 CLI 取消信息。"""
    print(f"已取消：{context}", file=sys.stderr)


def _is_explicit_path(value: str) -> bool:
    """判断登录态参数是否是显式文件路径。"""
    raw = Path(value)
    return raw.is_absolute() or "/" in value or "\\" in value


def _resolve_auth_state_path(value: str) -> Path:
    """解析登录态名称或 storage_state 文件路径。"""
    if _is_explicit_path(value):
        return resolve_project_path(value)
    filename = value if value.lower().endswith(".json") else f"{value}.json"
    return BROWSER_STATES_DIR / filename


def _auth_state_name_from_url(url: str) -> str:
    """从登录 URL 生成易读且可作为文件名的登录态名称。"""
    parsed = urlparse(url)
    site = (parsed.netloc or parsed.hostname or "default").rsplit("@", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]+", "-", site).strip(".-_") or "default"


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
            _print_cli_error(
                "大模型配置失败",
                llm_message("api_key_required"),
                "请重新执行 argus config llm 并输入 API Key。",
            )
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
        _print_cli_error(
            "大模型配置失败",
            f"数值配置格式错误：{exc}",
            "请检查最大输出 Token 数、温度和最大重试次数。",
        )
        return 1

    _write_env_values(env_path, updates)
    print(llm_message("saved"))
    print(llm_message("verify_hint"))
    print("argus llm check")
    return 0


def _run_serve(args: argparse.Namespace) -> int:
    """启动 FastAPI Web 服务。"""
    try:
        import uvicorn
    except ImportError:
        _print_cli_error(
            "Web 服务启动失败",
            "缺少 uvicorn 依赖。",
            '请先安装项目依赖，例如：pip install -e ".[dev]"',
        )
        return 1

    from argus_py.api.dependencies import SERVER_CONFIG_ENV, load_server_settings

    os.environ[SERVER_CONFIG_ENV] = str(resolve_project_path(args.config))
    settings = load_server_settings(args.config)
    host = args.host or settings.host
    port = args.port or settings.port
    reload_enabled = args.reload if args.reload is not None else settings.reload

    print(f"启动 Web 服务：http://{host}:{port}")
    print("OpenAPI 文档：/docs")
    uvicorn.run(
        "argus_py.api.app:app",
        host=host,
        port=port,
        reload=reload_enabled,
    )
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
        _print_cli_error(
            "LLM 检查超时",
            f"超过 {args.timeout:g} 秒未完成。",
            "请检查接口地址、代理或网络连接；也可以用 --timeout 临时调大等待时间。",
        )
        return 1

    print(f"模型：{response.model}")
    print(f"结束原因：{response.finish_reason}")
    print(f"Token：{response.usage.to_dict()}")
    print("响应内容：")
    print(response.content)
    return 0


async def _run_auth_save(args: argparse.Namespace) -> int:
    """打开登录页面，等待用户登录后保存 storage_state。"""
    if args.headed and args.headless:
        _print_cli_error("登录态保存失败", "--headed 和 --headless 不能同时使用。")
        return 1

    auth_state_name = args.name or _auth_state_name_from_url(args.url)
    auth_state_path = _resolve_auth_state_path(auth_state_name)
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
            _print_cli_error("登录态保存失败", "当前终端无法读取确认输入。")
            return 1
        if session.context is None:
            _print_cli_error("登录态保存失败", "浏览器上下文未创建。")
            return 1
        await session.context.storage_state(path=str(auth_state_path))

    print(f"登录态已保存：{auth_state_path}")
    print(f"登录态名称：{auth_state_name}")
    print(f"运行任务时可使用：argus run --auth-state {auth_state_name} --goal \"...\" --url \"...\"")
    return 0


def _run_auth_list() -> int:
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


async def _run_task(args: argparse.Namespace) -> int:
    """创建并执行黑盒任务。"""
    service = TaskService()
    limits = resolve_execution_limits(args.goal, args.url, args.max_steps, args.timeout)
    auth_state_arg = getattr(args, "auth_state", None)
    auth_state_path = _resolve_auth_state_path(auth_state_arg) if auth_state_arg else None
    if auth_state_path is not None and not auth_state_path.exists():
        _print_cli_error(
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
        _print_cli_error("任务执行失败", exc)
        return 1
    except KeyboardInterrupt:
        latest = service.cancel_task(task.task_id)
        _print_task_result(latest)
        _print_cli_cancelled("任务执行")
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


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        try:
            return _run_serve(args)
        except KeyboardInterrupt:
            _print_cli_cancelled("Web 服务")
            return 130
        except Exception as exc:
            _print_cli_error("Web 服务启动失败", exc)
            return 1

    if args.command == "run":
        try:
            return asyncio.run(_run_task(args))
        except KeyboardInterrupt:
            _print_cli_cancelled("任务执行")
            return 130
        except Exception as exc:
            _print_cli_error("任务执行失败", exc)
            return 1

    if args.command == "browser":
        if args.browser_command == "check":
            try:
                return asyncio.run(_run_browser_check(args))
            except Exception as exc:
                _print_cli_error("浏览器检查失败", exc)
                return 1
        parser.print_help()
        return 0

    if args.command == "auth":
        if args.auth_command == "save":
            try:
                return asyncio.run(_run_auth_save(args))
            except KeyboardInterrupt:
                _print_cli_cancelled("登录态保存")
                return 130
            except Exception as exc:
                _print_cli_error("登录态保存失败", exc)
                return 1
        if args.auth_command == "list":
            return _run_auth_list()
        parser.print_help()
        return 0

    if args.command == "llm":
        if args.llm_command == "check":
            try:
                return asyncio.run(_run_llm_check(args))
            except KeyboardInterrupt:
                _print_cli_cancelled("LLM 检查")
                return 130
            except Exception as exc:
                _print_cli_error("LLM 检查失败", exc)
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
