"""LLM 边界工厂：为任务解析 planner/evaluator 使用的 LLM client。"""

from __future__ import annotations

import logging

from argus_py.blackbox.evaluator import BlackboxEvaluator
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.llm.client import LLMClient
from argus_py.llm.resolver import resolve_llm_client_for_task
from argus_py.task.models import Task

logger = logging.getLogger(__name__)


class LLMBoundaryFactory:
    """为任务解析 planner 和 evaluator 的 LLM client。

    若本次 resolve 由内部新建了 LLMClient（以便其底层 httpx.AsyncClient 能在
    任务期间复用 keep-alive），调用方应在任务结束后调用 ``aclose_owned()``
    关闭这些“自有”client；外部注入的 default_planner / default_evaluator
    所携带的 client 不在此清理之列，避免误关掉调用方持有的连接池。
    """

    def __init__(
        self,
        default_planner: BlackboxPlanner | None = None,
        default_evaluator: BlackboxEvaluator | None = None,
    ) -> None:
        self._default_planner = default_planner
        self._default_evaluator = default_evaluator
        self._owned_clients: list[LLMClient] = []

    def resolve(self, task: Task) -> tuple[BlackboxPlanner, BlackboxEvaluator]:
        """为任务创建（或复用）planner 和 evaluator。"""
        planner = self._default_planner
        evaluator = self._default_evaluator

        if planner is None or evaluator is None:
            llm_client = resolve_llm_client_for_task(task)
            self._owned_clients.append(llm_client)
            if planner is None:
                planner = BlackboxPlanner(llm_client=llm_client)
            if evaluator is None:
                evaluator = BlackboxEvaluator(llm_client=llm_client)

        return planner, evaluator

    async def aclose_owned(self) -> None:
        """关闭本工厂创建的 LLMClient 底层连接池，可重复调用。"""
        clients = self._owned_clients
        self._owned_clients = []
        for client in clients:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                logger.debug("关闭自有 LLMClient 时忽略异常", exc_info=True)
