"""动作失败恢复策略。"""

from __future__ import annotations

from enum import Enum, auto

from argus_py.core.exceptions import TaskError


class RecoveryAction(Enum):
    """动作失败后的恢复决策。"""

    # 参数/URL 校验失败：直接重新观察并规划，不计数
    REPLAN = auto()
    # 一般执行异常：重新观察，计数重试
    RETRY = auto()
    # 超出重试上限：中止，向外传播异常
    ABORT = auto()


class RecoveryPolicy:
    """判断动作失败后应如何恢复。"""

    # 应直接重新规划（不消耗重试次数）的错误码
    _REPLAN_ERROR_CODES = frozenset(
        {
            "empty_url",
            "invalid_scheme",
            "malformed_url",
            "markdown_link_text",
            "plain_text",
            "param_invalid",
        }
    )

    def __init__(self, max_attempts: int = 2) -> None:
        self.max_attempts = max_attempts

    def decide(self, error: TaskError, recovery_attempts: int) -> RecoveryAction:
        """根据错误类型和已重试次数返回恢复决策。"""
        if error.error_code in self._REPLAN_ERROR_CODES:
            return RecoveryAction.REPLAN
        if recovery_attempts >= self.max_attempts:
            return RecoveryAction.ABORT
        return RecoveryAction.RETRY
