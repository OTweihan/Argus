"""黑盒 Agent 执行器（门面）。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from argus_py.blackbox.action_executor import ActionExecutor
from argus_py.blackbox.evaluator import BlackboxEvaluator
from argus_py.blackbox.events import BlackboxEvents
from argus_py.blackbox.evidence import EvidenceCollector
from argus_py.blackbox.execution_loop import BlackboxExecutionLoop
from argus_py.blackbox.finalizer import Finalizer
from argus_py.blackbox.llm_boundary import LLMBoundaryFactory
from argus_py.blackbox.models import BlackboxTaskInput
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.blackbox.recovery import RecoveryPolicy
from argus_py.browser import BrowserSession
from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import TaskError
from argus_py.core.paths import SCREENSHOTS_DIR
from argus_py.observability.context import bind_context
from argus_py.report.generator import ReportGenerator
from argus_py.task.models import Task
from argus_py.task.service import TaskService

logger = logging.getLogger(__name__)

BrowserSessionFactory = Callable[[Task], BrowserSession]


class BlackboxRunner:
    """串联规划、浏览器和评估的黑盒 Agent 执行器（门面，委托子组件）。"""

    def __init__(
        self,
        service: TaskService | None = None,
        planner: BlackboxPlanner | None = None,
        evaluator: BlackboxEvaluator | None = None,
        browser_session_factory: BrowserSessionFactory | None = None,
        report_generator: ReportGenerator | None = None,
        max_plan_steps: int = 3,
        max_recovery_attempts: int = 2,
        model_config_service: ModelConfigService | None = None,
    ) -> None:
        self.service = service or TaskService()
        self.planner = planner or BlackboxPlanner()
        self.evaluator = evaluator or BlackboxEvaluator()
        self.browser_session_factory = browser_session_factory or self._default_browser_session
        self.max_plan_steps = max_plan_steps
        self._model_config_service = model_config_service

        self.evidence = EvidenceCollector()
        self.action_executor = ActionExecutor(self.service, self.evidence)
        self.finalizer = Finalizer(self.service, report_generator)
        self.events = BlackboxEvents(self.service)
        self.recovery_policy = RecoveryPolicy(max_attempts=max_recovery_attempts)
        self.llm_boundary = LLMBoundaryFactory(
            default_planner=None if planner is None else planner,
            default_evaluator=None if evaluator is None else evaluator,
            model_config_service=model_config_service,
        )

    async def run(self, task: Task | BlackboxTaskInput) -> Task:
        """执行黑盒任务闭环。"""
        resolved = self._resolve_task(task)
        owns_status = resolved.status is TaskStatus.PENDING
        if resolved.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            raise TaskError(f"黑盒任务状态不允许执行：{resolved.status.value}")
        if owns_status:
            resolved = self.service.start_task(resolved)

        self.events.task_start(resolved.task_id, resolved.goal, resolved.start_url or "")

        planner, evaluator = self.llm_boundary.resolve(resolved)
        task_input = self._to_task_input(resolved)

        loop = BlackboxExecutionLoop(
            service=self.service,
            action_executor=self.action_executor,
            finalizer=self.finalizer,
            evidence=self.evidence,
            events=self.events,
            recovery_policy=self.recovery_policy,
            max_plan_steps=self.max_plan_steps,
        )

        with bind_context(task_id=resolved.task_id):
            try:
                async with self.browser_session_factory(resolved) as session:
                    resolved = await loop.run(
                        resolved, task_input, planner, evaluator, session, owns_status
                    )
            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception as exc:
                logger.exception("黑盒任务异常：%s", resolved.task_id)
                latest = self.service.get_latest_task(resolved)
                if owns_status and latest.status is TaskStatus.RUNNING:
                    self.events.fail(resolved.task_id, str(exc))
                    failed = self.service.fail_task(latest, str(exc))
                    self.finalizer.generate_report(failed)
                raise
            finally:
                # 关闭本任务期间由 LLMBoundaryFactory 自建的 LLMClient，
                # 释放底层 httpx.AsyncClient 连接池；外部注入的 client 不会被关闭。
                await self.llm_boundary.aclose_owned(resolved.task_id)

        return resolved

    def _resolve_task(self, task: Task | BlackboxTaskInput) -> Task:
        """统一任务输入。"""
        if isinstance(task, Task):
            return task
        parameters: dict[str, str | dict[str, str]] = {}
        if task.prompt_extensions:
            parameters["prompt_extensions"] = dict(task.prompt_extensions)
        return self.service.create_task(
            goal=task.goal,
            start_url=task.start_url,
            max_steps=task.max_steps,
            timeout_seconds=task.timeout_seconds,
            capture_screenshots=task.capture_screenshots,
            parameters=parameters or None,
        )

    def _to_task_input(self, task: Task) -> BlackboxTaskInput:
        """从任务实体构造黑盒输入。"""
        if not task.start_url:
            raise TaskError("黑盒任务缺少起始 URL。")
        return BlackboxTaskInput(
            goal=task.goal,
            start_url=task.start_url,
            max_steps=task.max_steps,
            timeout_seconds=task.timeout_seconds,
            capture_screenshots=task.capture_screenshots,
        )

    def _default_browser_session(self, task: Task) -> BrowserSession:
        """创建默认浏览器会话。"""
        screenshot_dir: Path = SCREENSHOTS_DIR / task.task_id
        return BrowserSession(screenshot_dir=screenshot_dir)
