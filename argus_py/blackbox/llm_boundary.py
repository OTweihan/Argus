"""LLM 边界工厂：为任务解析 planner/evaluator 使用的 LLM client。"""

from __future__ import annotations

from argus_py.blackbox.evaluator import BlackboxEvaluator
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.llm.resolver import resolve_llm_client_for_task
from argus_py.task.models import Task


class LLMBoundaryFactory:
    """为任务解析 planner 和 evaluator 的 LLM client。"""

    def __init__(
        self,
        default_planner: BlackboxPlanner | None = None,
        default_evaluator: BlackboxEvaluator | None = None,
    ) -> None:
        self._default_planner = default_planner
        self._default_evaluator = default_evaluator

    def resolve(self, task: Task) -> tuple[BlackboxPlanner, BlackboxEvaluator]:
        """为任务创建（或复用）planner 和 evaluator。"""
        planner = self._default_planner
        evaluator = self._default_evaluator

        if planner is None or evaluator is None:
            llm_client = resolve_llm_client_for_task(task)
            if planner is None:
                planner = BlackboxPlanner(llm_client=llm_client)
            if evaluator is None:
                evaluator = BlackboxEvaluator(llm_client=llm_client)

        return planner, evaluator
