"""LLM 边界工厂：为任务解析 planner/evaluator 使用的 LLM client。"""

from __future__ import annotations

import logging
from typing import Any

from argus_py.blackbox.evaluator import BlackboxEvaluator
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.core.exceptions import ProjectNotFoundError
from argus_py.llm.client import LLMClient
from argus_py.llm.resolver import resolve_llm_client_for_task
from argus_py.observability.events import STATUS_ERROR, log_event
from argus_py.project.storage import ProjectSQLiteStorage
from argus_py.task.models import Task

logger = logging.getLogger(__name__)

PROMPT_EXTENSION_KEY = "prompt_extensions"


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
        project_storage: ProjectSQLiteStorage | None = None,
    ) -> None:
        self._default_planner = default_planner
        self._default_evaluator = default_evaluator
        self._project_storage = project_storage
        self._owned_clients: list[LLMClient] = []

    def resolve(self, task: Task) -> tuple[BlackboxPlanner, BlackboxEvaluator]:
        """为任务创建（或复用）planner 和 evaluator。"""
        planner = self._default_planner
        evaluator = self._default_evaluator

        if planner is None or evaluator is None:
            llm_client = resolve_llm_client_for_task(task)
            self._owned_clients.append(llm_client)
            planner_exts, evaluator_exts = self._collect_extensions(task)
            if planner is None:
                planner = BlackboxPlanner(llm_client=llm_client, prompt_extensions=planner_exts)
            if evaluator is None:
                evaluator = BlackboxEvaluator(
                    llm_client=llm_client, prompt_extensions=evaluator_exts
                )

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

    def _collect_extensions(self, task: Task) -> tuple[list[str], list[str]]:
        """按 [project, task] 顺序收集 planner / evaluator 的 prompt 扩展片段。"""
        project_ext = self._load_project_extensions(task.project_id)
        task_ext = _extract_extension_map(task.parameters)

        planner_exts = _ordered_extensions("planner", project_ext, task_ext)
        evaluator_exts = _ordered_extensions("evaluator", project_ext, task_ext)
        return planner_exts, evaluator_exts

    def _load_project_extensions(self, project_id: str | None) -> dict[str, str]:
        """从 project.parameters 读取 prompt 扩展；加载失败时降级为空。

        P1-9：区分两类失败：
        - ``ProjectNotFoundError``：项目根本不存在。可能是任务历史数据指向已删项目，
          也可能是 task 直接传了无效 ``project_id``；这属于"未配置扩展"语义，
          只 debug 不 warn，避免噪声。
        - 其它异常（DB 不可用 / 加密 key 缺失 / 字段反序列化失败等）：可能影响整批
          任务的扩展功能，升 warning + ``log_event`` 留下结构化排障线索。
        """
        if not project_id:
            return {}
        try:
            storage = self._project_storage or ProjectSQLiteStorage()
            project = storage.load(project_id)
        except ProjectNotFoundError:
            # 仅"未配置/已删除"语义：debug 级即可
            logger.debug("项目不存在，按无 prompt 扩展处理：project_id=%s", project_id)
            return {}
        except Exception as exc:  # noqa: BLE001
            # 真正的环境/存储异常：warning + 结构化事件，便于巡检和告警
            log_event(
                logger,
                "prompt_extension.load",
                status=STATUS_ERROR,
                details={
                    "projectId": project_id,
                    "errorType": type(exc).__name__,
                },
                message="读取项目 prompt 扩展失败，按无扩展继续执行任务。",
                exc_info=True,
            )
            return {}
        return _extract_extension_map(project.parameters)


def _extract_extension_map(parameters: dict[str, Any] | None) -> dict[str, str]:
    """从 parameters 字典提取 prompt_extensions 子结构。"""
    if not parameters:
        return {}
    raw = parameters.get(PROMPT_EXTENSION_KEY)
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            result[str(key)] = value
    return result


def _ordered_extensions(
    role: str, project_ext: dict[str, str], task_ext: dict[str, str]
) -> list[str]:
    """按 [project, task] 顺序返回非空扩展。"""
    return [ext for ext in (project_ext.get(role, ""), task_ext.get(role, "")) if ext]
