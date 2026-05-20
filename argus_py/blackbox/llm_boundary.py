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
    任务期间复用 keep-alive），调用方应在任务结束后调用 ``aclose_owned(task_id)``
    关闭这些"自有"client；外部注入的 default_planner / default_evaluator
    所携带的 client 不在此清理之列，避免误关掉调用方持有的连接池。

    ``_owned_clients`` 按 ``task_id`` 索引，避免并发任务互相干扰。
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
        self._owned_clients: dict[str, list[LLMClient]] = {}

    def resolve(self, task: Task) -> tuple[BlackboxPlanner, BlackboxEvaluator]:
        """为任务创建（或复用）planner 和 evaluator。

        当外部注入的 planner/evaluator ``llm_client is None`` 时，惰性
        ``_client()`` 会各自创建独立的 ``LLMClient``，导致底层 httpx 连接池
        泄漏。本方法注入工厂托管的共享 client 以阻断惰性加载路径。
        """
        planner = self._default_planner
        evaluator = self._default_evaluator

        # 注意：外部可能传入无 llm_client 属性的 Mock/stub 对象，
        # 使用 hasattr 安全探测。
        def _needs_client(obj: Any) -> bool:
            return obj is None or (hasattr(obj, "llm_client") and obj.llm_client is None)

        if _needs_client(planner) or _needs_client(evaluator):
            llm_client = resolve_llm_client_for_task(task)
            self._owned_clients.setdefault(task.task_id, []).append(llm_client)
            planner_exts, evaluator_exts = self._collect_extensions(task)

            if planner is None:
                planner = BlackboxPlanner(llm_client=llm_client, prompt_extensions=planner_exts)
            elif hasattr(planner, "llm_client") and planner.llm_client is None:
                planner.llm_client = llm_client

            if evaluator is None:
                evaluator = BlackboxEvaluator(
                    llm_client=llm_client, prompt_extensions=evaluator_exts
                )
            elif hasattr(evaluator, "llm_client") and evaluator.llm_client is None:
                evaluator.llm_client = llm_client

        # _needs_client 都为 False 意味着双方非 None，但 mypy 无法从辅助
        # 函数中推断窄化，用断言保证类型安全。
        assert planner is not None
        assert evaluator is not None
        return planner, evaluator

    async def aclose_owned(self, task_id: str | None = None) -> None:
        """关闭本工厂创建的 LLMClient 底层连接池。

        指定 ``task_id`` 时只关闭该任务的自有 client，避免并发任务互相干扰；
        不传则关闭全部（向后兼容）。
        """
        if task_id is not None:
            clients = self._owned_clients.pop(task_id, [])
        else:
            clients = []
            for tid in list(self._owned_clients):
                clients.extend(self._owned_clients.pop(tid))
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

        区分两类失败：
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
