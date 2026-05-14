"""``BlackboxExecutionLoop`` 使用的恢复策略 ``RecoveryPolicy`` 决策矩阵单测。"""

from __future__ import annotations

import pytest

from argus_py.blackbox.recovery import RecoveryAction, RecoveryPolicy
from argus_py.core.exceptions import TaskError


@pytest.mark.parametrize(
    "code",
    [
        "empty_url",
        "invalid_scheme",
        "malformed_url",
        "markdown_link_text",
        "plain_text",
        "param_invalid",
    ],
)
def test_replan_codes_short_circuit_to_replan(code: str) -> None:
    """所有 _REPLAN_ERROR_CODES 中的错误码不消耗重试次数，直接重新规划。"""
    policy = RecoveryPolicy(max_attempts=2)
    decision = policy.decide(TaskError("...", error_code=code), recovery_attempts=99)
    assert decision is RecoveryAction.REPLAN


def test_unknown_error_within_max_attempts_retries() -> None:
    """非 REPLAN 错误码且重试未达上限 → RETRY。"""
    policy = RecoveryPolicy(max_attempts=2)
    decision = policy.decide(TaskError("network", error_code="net_io"), recovery_attempts=0)
    assert decision is RecoveryAction.RETRY


def test_unknown_error_at_max_attempts_aborts() -> None:
    """非 REPLAN 错误码且重试已达上限 → ABORT。"""
    policy = RecoveryPolicy(max_attempts=2)
    decision = policy.decide(TaskError("network", error_code="net_io"), recovery_attempts=2)
    assert decision is RecoveryAction.ABORT


def test_no_error_code_falls_through_to_retry_or_abort() -> None:
    """没有 error_code 不命中 REPLAN 集合，按重试次数走 RETRY/ABORT。"""
    policy = RecoveryPolicy(max_attempts=1)
    error = TaskError("oops")
    assert error.error_code is None
    assert policy.decide(error, recovery_attempts=0) is RecoveryAction.RETRY
    assert policy.decide(error, recovery_attempts=1) is RecoveryAction.ABORT
