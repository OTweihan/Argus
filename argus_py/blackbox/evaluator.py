"""黑盒执行结果评估器。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvaluationResult:
    """评估结果。"""

    completed: bool
    success: bool
    reason: str = ""


class BlackboxEvaluator:
    """判断目标是否完成的边界。"""

    async def evaluate(self, goal: str, observation: str) -> EvaluationResult:
        """MVP 骨架默认交给后续 LLM 评估实现。"""
        return EvaluationResult(completed=False, success=False, reason="评估器尚未接入 LLM。")
