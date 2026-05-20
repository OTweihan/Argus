"""任务状态业务规则：共享谓词，避免应用层与生命周期层校验漂移。"""

from __future__ import annotations

from argus_py.core.enums import TaskStatus


def can_edit(status: TaskStatus) -> bool:
    """只有 pending 状态的任务可以编辑字段。"""
    return status is TaskStatus.PENDING


def can_delete(status: TaskStatus) -> bool:
    """只有 pending 状态的任务可以删除。"""
    return status is TaskStatus.PENDING


def can_start(status: TaskStatus) -> bool:
    """只有 pending 状态的任务可以启动。"""
    return status is TaskStatus.PENDING


def can_retry(status: TaskStatus) -> bool:
    """只有失败/超时/取消的任务可以重试。"""
    return status in (TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED)


def can_pause(status: TaskStatus) -> bool:
    """只有运行中的任务可以暂停。"""
    return status is TaskStatus.RUNNING


def can_resume(status: TaskStatus) -> bool:
    """只有已暂停的任务可以恢复。"""
    return status is TaskStatus.PAUSED


def is_terminal(status: TaskStatus) -> bool:
    """终态：不允许再流转。"""
    return status in (
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.CANCELLED,
    )
