"""黑盒 Agent 执行器。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from argus_py.blackbox.action_executor import ActionExecutor
from argus_py.blackbox.evaluator import BlackboxEvaluator
from argus_py.blackbox.evidence import EvidenceCollector
from argus_py.blackbox.finalizer import Finalizer
from argus_py.blackbox.models import ActionSequence, BlackboxTaskInput
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.browser import BrowserSession
from argus_py.browser.snapshot import redact_href
from argus_py.core.cancellation import CancellationToken
from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import TaskError
from argus_py.core.paths import SCREENSHOTS_DIR
from argus_py.llm.resolver import resolve_llm_client_for_task
from argus_py.report.generator import ReportGenerator
from argus_py.task.models import Task
from argus_py.task.service import TaskService

logger = logging.getLogger(__name__)

BrowserSessionFactory = Callable[[Task], BrowserSession]


class BlackboxRunner:
    """串联规划、浏览器和评估的黑盒 Agent 执行器。"""

    def __init__(
        self,
        service: TaskService | None = None,
        planner: BlackboxPlanner | None = None,
        evaluator: BlackboxEvaluator | None = None,
        browser_session_factory: BrowserSessionFactory | None = None,
        report_generator: ReportGenerator | None = None,
        max_plan_steps: int = 3,
        max_recovery_attempts: int = 2,
    ) -> None:
        self.service = service or TaskService()
        self.planner = planner or BlackboxPlanner()
        self.evaluator = evaluator or BlackboxEvaluator()
        self._uses_default_planner = planner is None
        self._uses_default_evaluator = evaluator is None
        self.browser_session_factory = browser_session_factory or self._default_browser_session
        self.max_plan_steps = max_plan_steps
        self.max_recovery_attempts = max_recovery_attempts
        self.evidence = EvidenceCollector()
        self.action_executor = ActionExecutor(self.service, self.evidence)
        self.finalizer = Finalizer(self.service, report_generator)
        self._last_error: dict[str, Any] | None = None

    async def run(self, task: Task | BlackboxTaskInput) -> Task:
        """执行黑盒任务闭环。"""
        resolved = self._resolve_task(task)
        owns_status = resolved.status is TaskStatus.PENDING
        if resolved.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            raise TaskError(f"黑盒任务状态不允许执行：{resolved.status.value}")
        if owns_status:
            resolved = self.service.start_task(resolved)

        planner, evaluator = self._resolve_llm_boundaries(resolved)
        task_input = self._to_task_input(resolved)
        sequence = await planner.plan_initial(task_input)

        try:
            async with self.browser_session_factory(resolved) as session:
                latest_observation = ""
                executed_steps = 0
                recovery_attempts = 0

                while executed_steps < task_input.max_steps:
                    if await self._check_cancelled(resolved):
                        resolved = self.service.get_latest_task(resolved)
                        return self.finalizer.finalize(resolved, owns_status)
                    if not sequence.steps:
                        sequence = await self._plan_next(resolved, latest_observation, planner)
                        if not sequence.steps:
                            raise TaskError("规划器未返回可执行动作。")

                    for action_step in sequence.steps:
                        if executed_steps >= task_input.max_steps:
                            break
                        executed_steps += 1

                        try:
                            resolved, latest_observation = (
                                await self.action_executor.execute_action(
                                    resolved, session, action_step
                                )
                            )
                            recovery_attempts = 0
                            self._last_error = None
                        except TaskError as exc:
                            resolved = self.service.get_latest_task(resolved)
                            self._last_error = {
                                "action": action_step.action.value,
                                "error_code": exc.error_code,
                                "error_message": str(exc),
                                "step_number": executed_steps,
                            }
                            if exc.error_code in (
                                "empty_url",
                                "invalid_scheme",
                                "malformed_url",
                                "markdown_link_text",
                                "plain_text",
                                "param_invalid",
                            ):
                                latest_observation = await self.evidence.safe_observation(session)
                                sequence = ActionSequence(
                                    steps=[], summary=f"参数校验失败：{exc}，重新规划。"
                                )
                                break
                            if recovery_attempts >= self.max_recovery_attempts:
                                raise
                            recovery_attempts += 1
                            latest_observation = await self.evidence.safe_observation(session)
                            sequence = ActionSequence(
                                steps=[],
                                summary="动作失败后重新观察页面并规划。",
                            )
                            break

                    if not sequence.steps:
                        continue

                    evaluation = await evaluator.evaluate(
                        resolved.goal,
                        latest_observation,
                        history=self.finalizer.history(resolved),
                    )
                    resolved = self.finalizer.append_evaluation(resolved, evaluation)
                    if evaluation.completed:
                        resolved.result_summary = evaluation.reason
                        if evaluation.success:
                            return self.finalizer.finish_success(resolved, owns_status)
                        raise TaskError(evaluation.reason or "黑盒任务已完成，但评估结果为失败。")

                    if executed_steps >= task_input.max_steps:
                        break
                    sequence = await self._plan_next(resolved, latest_observation, planner)
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except Exception as exc:
            logger.exception("黑盒任务异常：%s", resolved.task_id)
            latest = self.service.get_latest_task(resolved)
            if owns_status and latest.status is TaskStatus.RUNNING:
                failed = self.service.fail_task(latest, str(exc))
                self.finalizer.generate_report(failed)
            raise

        message = f"达到最大步骤 {task_input.max_steps} 后仍未完成目标。"
        latest = self.service.get_latest_task(resolved)
        if owns_status and latest.status is TaskStatus.RUNNING:
            failed = self.service.fail_task(latest, message)
            self.finalizer.generate_report(failed)
        raise TaskError(message)

    def _resolve_task(self, task: Task | BlackboxTaskInput) -> Task:
        """统一任务输入。"""
        if isinstance(task, Task):
            return task
        return self.service.create_task(
            goal=task.goal,
            start_url=task.start_url,
            max_steps=task.max_steps,
            timeout_seconds=task.timeout_seconds,
            capture_screenshots=task.capture_screenshots,
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

    async def _plan_next(
        self,
        task: Task,
        latest_observation: str,
        planner: BlackboxPlanner,
    ) -> ActionSequence:
        """请求规划器生成下一批动作，携带上一轮失败信息。"""
        if task.logs and task.logs[-1].url_after:
            current_url = redact_href(task.logs[-1].url_after)
        else:
            current_url = redact_href(task.start_url or "")
        last_error = self._last_error
        self._last_error = None
        return await planner.plan_next(
            goal=task.goal,
            current_url=current_url,
            page_snapshot=latest_observation,
            history=self.finalizer.history(task),
            max_steps=self.max_plan_steps,
            last_error=last_error,
        )

    def _resolve_llm_boundaries(self, task: Task) -> tuple[BlackboxPlanner, BlackboxEvaluator]:
        """为当前任务解析 LLM 边界，默认实现按模型配置创建独立客户端。"""
        if not self._uses_default_planner and not self._uses_default_evaluator:
            return self.planner, self.evaluator
        llm_client = resolve_llm_client_for_task(task)
        planner = (
            self.planner
            if not self._uses_default_planner
            else BlackboxPlanner(llm_client=llm_client)
        )
        evaluator = (
            self.evaluator
            if not self._uses_default_evaluator
            else BlackboxEvaluator(llm_client=llm_client)
        )
        return planner, evaluator

    async def _check_cancelled(self, task: Task) -> bool:
        """检查任务是否被外部取消或暂停。返回 True 表示应停止执行。"""
        token: CancellationToken = self.service.get_cancellation_token(task.task_id)
        if token.is_cancelled:
            return True
        if token.is_paused:
            await token.wait_if_paused()
            latest = self.service.get_latest_task(task)
            return latest.status is not TaskStatus.RUNNING
        return False

    def _default_browser_session(self, task: Task) -> BrowserSession:
        """创建默认浏览器会话。"""
        screenshot_dir: Path = SCREENSHOTS_DIR / task.task_id
        return BrowserSession(screenshot_dir=screenshot_dir)
