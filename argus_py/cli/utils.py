"""CLI 共享工具函数。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from argus_py.cli.io import cli_cancelled, cli_error
from argus_py.core.paths import BROWSER_STATES_DIR, resolve_project_path

if TYPE_CHECKING:
    from argus_py.core.models import Task
    from argus_py.task.read import TaskReadService


def positive_int(value: str) -> int:
    """解析正整数命令行参数。"""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是正整数。") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数。")
    return number


def print_cli_error(context: str, detail: object | None = None, hint: str | None = None) -> None:
    """统一输出 CLI 错误信息（向后兼容别名，委托给 :func:`cli_error`）。"""
    cli_error(context, detail, hint)


def print_cli_cancelled(context: str) -> None:
    """统一输出 CLI 取消信息（向后兼容别名，委托给 :func:`cli_cancelled`）。"""
    cli_cancelled(context)


def is_explicit_path(value: str) -> bool:
    """判断登录态参数是否是显式文件路径。"""
    raw = Path(value)
    return raw.is_absolute() or "/" in value or "\\" in value


def resolve_auth_state_path(value: str) -> Path:
    """解析登录态名称或 storage_state 文件路径。"""
    if is_explicit_path(value):
        return resolve_project_path(value)
    filename = value if value.lower().endswith(".json") else f"{value}.json"
    return BROWSER_STATES_DIR / filename


def load_latest_task(reader: TaskReadService, task: Task) -> Task:
    """读取最新任务快照，失败时回退到原始 task 对象。"""
    from argus_py.core.exceptions import TaskError

    try:
        return reader.get_task(task.task_id)
    except TaskError:
        return task


def auth_state_name_from_url(url: str) -> str:
    """从登录 URL 生成易读且可作为文件名的登录态名称。"""
    parsed = urlparse(url)
    site = (parsed.netloc or parsed.hostname or "default").rsplit("@", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]+", "-", site).strip(".-_") or "default"
