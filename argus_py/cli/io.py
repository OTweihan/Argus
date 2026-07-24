"""CLI 用户输出层。

把 CLI 命令面向最终用户的输出收敛到这里，与后端 logger 解耦：

- ``cli_print`` / ``cli_success`` / ``cli_warn`` / ``cli_error`` / ``cli_cancelled``
  对应不同语义，统一走 ``stdout`` / ``stderr``。
- 内部仍可使用 ``logging.getLogger(...)`` 记录调试信息；这两套渠道彼此
  独立，CLI 一次性命令默认不会把 logger 输出与用户输出混在一起。
- ``setup_cli_logging`` 提供 CLI 专用的精简日志配置：只走 console，
  默认 WARNING，``--verbose`` 时降到 INFO/DEBUG，避免和 server 进程
  争抢 ``outputs/logs/runtime/python/argus.log``。
"""

from __future__ import annotations

import logging
import sys
from typing import Any


def cli_print(message: str, **kwargs: Any) -> None:
    """打印一条普通信息到 stdout。"""
    print(message, **kwargs)


def cli_success(message: str) -> None:
    """打印一条成功信息到 stdout。"""
    print(message)


def cli_info(message: str) -> None:
    """打印一条状态信息到 stdout（与 cli_print 等价，仅语义更明确）。"""
    print(message)


def cli_warn(message: str) -> None:
    """打印一条警告信息到 stderr。"""
    print(f"警告：{message}", file=sys.stderr)


def cli_error(context: str, detail: object | None = None, hint: str | None = None) -> None:
    """打印一条错误信息到 stderr，统一格式：context / 详情 / 提示。"""
    print(f"错误：{context}", file=sys.stderr)
    if detail:
        print(f"详情：{detail}", file=sys.stderr)
    if hint:
        print(f"提示：{hint}", file=sys.stderr)


def cli_cancelled(context: str) -> None:
    """打印一条取消信息到 stderr。"""
    print(f"已取消：{context}", file=sys.stderr)


def setup_cli_logging(verbose: int = 0) -> None:
    """为 CLI 一次性命令配置精简日志：仅 console，无文件输出。

    Args:
        verbose: 详细程度。0 → WARNING（默认，几乎只看到用户输出）；
            1 → INFO；>=2 → DEBUG。
    """
    if verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in ("argus_py", "argus"):
        target = logging.getLogger(name)
        target.handlers = []
        target.setLevel(level)
        target.propagate = True

    # 第三方库继续保持安静
    for name in ("httpx", "httpcore", "asyncio", "watchfiles", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)


def print_task_result(task: Any, show_steps: bool = False) -> None:
    """输出任务执行结果。

    适用黑盒和白盒两类任务，通过 show_steps 控制是否打印执行步骤数
    （白盒任务不适用）。
    """
    cli_print(f"任务 ID：{task.task_id}")
    cli_print(f"任务状态：{task.status.value}")
    if show_steps:
        cli_print(f"执行步骤：{task.current_step}")
    cli_print(f"问题数量：{len(task.findings)}")
    if task.result_summary:
        cli_print(f"结果摘要：{task.result_summary}")
    if task.report_path:
        cli_print(f"HTML 报告：{task.report_path}")
    if task.error_message:
        cli_print(f"错误信息：{task.error_message}")


__all__ = [
    "cli_cancelled",
    "cli_error",
    "cli_info",
    "cli_print",
    "cli_success",
    "cli_warn",
    "print_task_result",
    "setup_cli_logging",
]
