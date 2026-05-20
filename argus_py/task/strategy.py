"""任务执行策略。"""

from __future__ import annotations

from dataclasses import dataclass

from argus_py.core.constants import (
    DEFAULT_COMPLEX_TASK_STEPS,
    DEFAULT_COMPLEX_TASK_TIMEOUT_S,
    DEFAULT_NORMAL_TASK_STEPS,
    DEFAULT_NORMAL_TASK_TIMEOUT_S,
    DEFAULT_SIMPLE_TASK_STEPS,
    DEFAULT_SIMPLE_TASK_TIMEOUT_S,
)

SIMPLE_TASK_KEYWORDS = ("打开", "访问", "截图", "确认页面", "检查页面", "可访问", "title")
COMPLEX_TASK_KEYWORDS = (
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
)


@dataclass(frozen=True)
class TaskExecutionLimits:
    """任务执行限制。"""

    max_steps: int
    timeout_seconds: int


def infer_execution_limits(goal: str, url: str) -> TaskExecutionLimits:
    """根据任务描述保守推断步数和超时时间。"""
    text = f"{goal} {url}".lower()
    if any(keyword in text for keyword in COMPLEX_TASK_KEYWORDS):
        return TaskExecutionLimits(DEFAULT_COMPLEX_TASK_STEPS, DEFAULT_COMPLEX_TASK_TIMEOUT_S)
    if any(keyword in text for keyword in SIMPLE_TASK_KEYWORDS):
        return TaskExecutionLimits(DEFAULT_SIMPLE_TASK_STEPS, DEFAULT_SIMPLE_TASK_TIMEOUT_S)
    return TaskExecutionLimits(DEFAULT_NORMAL_TASK_STEPS, DEFAULT_NORMAL_TASK_TIMEOUT_S)


def resolve_execution_limits(
    goal: str,
    url: str,
    max_steps: int | None = None,
    timeout_seconds: int | None = None,
) -> TaskExecutionLimits:
    """合并用户显式限制和系统推断限制。"""
    inferred = infer_execution_limits(goal, url)
    return TaskExecutionLimits(
        max_steps=max_steps if max_steps is not None else inferred.max_steps,
        timeout_seconds=(
            timeout_seconds if timeout_seconds is not None else inferred.timeout_seconds
        ),
    )
