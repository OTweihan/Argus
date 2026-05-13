"""黑盒 Agent 执行循环：Planner → 动作执行 → Evaluator 闭环。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from argus_py.blackbox.action_executor import ActionExecutor
from argus_py.blackbox.evaluator import BlackboxEvaluator
from argus_py.blackbox.events import BlackboxEvents
from argus_py.blackbox.evidence import EvidenceCollector
from argus_py.blackbox.finalizer import Finalizer
from argus_py.blackbox.models import ActionSequence, BlackboxTaskInput
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.blackbox.recovery import RecoveryAction, RecoveryPolicy
from argus_py.browser import BrowserSession
from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import TaskError
from argus_py.redaction import redact_href
from argus_py.task.models import Task
from argus_py.task.service import TaskService

logger = logging.getLogger(__name__)


class BlackboxExecutionLoop:
    """Planner → 动作执行 → Evaluator 核心闭环。"""

    def __init__(
        self,
        service: TaskService,
        action_executor: ActionExecutor,
        finalizer: Finalizer,
        evidence: EvidenceCollector,
        events: BlackboxEvents,
        recovery_policy: RecoveryPolicy,
        max_plan_steps: int = 3,
        check_cancelled_fn: Callable[[Task], bool] | None = None,
    ) -> None:
        self.service = service
        self.action_executor = action_executor
        self.finalizer = finalizer
        self.evidence = evidence
        self.events = events
        self.recovery_policy = recovery_policy
        self.max_plan_steps = max_plan_steps
        self._check_cancelled_fn = check_cancelled_fn

    async def run(
        self,
        task: Task,
        task_input: BlackboxTaskInput,
        planner: BlackboxPlanner,
        evaluator: BlackboxEvaluator,
        session: BrowserSession,
        owns_status: bool,
    ) -> Task:
        """执行 Planner → 动作执行 → Evaluator 闭环，返回终态 Task。"""
        latest_observation = ""
        executed_steps = 0
        recovery_attempts = 0
        sequence: ActionSequence = ActionSequence(steps=[])
        _last_error: dict | None = None

        first_plan = True

        while executed_steps < task_input.max_steps:
            # ── 暂停/取消检测 ──
            if await self._check_cancelled(task):
                return self.finalizer.finalize(self.service.get_latest_task(task), owns_status)

            # ── 规划 ──
            if not sequence.steps:
                if first_plan:
                    sequence = await planner.plan_initial(task_input)
                    first_plan = False
                else:
                    sequence, _last_error = await self._plan_next(
                        task, latest_observation, planner, _last_error
                    )
                if not sequence.steps:
                    raise TaskError("规划器未返回可执行动作。")

            # ── 执行 ──
            for action_step in sequence.steps:
                if executed_steps >= task_input.max_steps:
                    break
                executed_steps += 1

                self.events.action(
                    task.task_id,
                    executed_steps,
                    action_step.action.value,
                    action_step.selector,
                    action_step.url,
                )

                try:
                    task, latest_observation = await self.action_executor.execute_action(
                        task, session, action_step
                    )
                    recovery_attempts = 0
                    _last_error = None
                except TaskError as exc:
                    task = self.service.get_latest_task(task)
                    _last_error = {
                        "action": action_step.action.value,
                        "error_code": exc.error_code,
                        "error_message": str(exc),
                        "step_number": executed_steps,
                    }

                    decision = self.recovery_policy.decide(exc, recovery_attempts)
                    if decision is RecoveryAction.ABORT:
                        raise
                    if decision is RecoveryAction.RETRY:
                        recovery_attempts += 1

                    latest_observation = await self.evidence.safe_observation(session)
                    sequence = ActionSequence(
                        steps=[],
                        summary=(
                            "参数校验失败：重新规划。"
                            if decision is RecoveryAction.REPLAN
                            else "动作失败后重新观察页面并规划。"
                        ),
                    )
                    break

            # 当前批次无可用步骤 → 重新规划
            if not sequence.steps:
                continue

            # ── 评估 ──
            self.events.evaluator_start(task.task_id, executed_steps, task.goal)

            evaluation = await evaluator.evaluate(
                task.goal,
                latest_observation,
                history=self.finalizer.history(task),
            )

            self.events.evaluator_result(
                task.task_id,
                executed_steps,
                evaluation.success,
                evaluation.completed,
                evaluation.reason,
                len(evaluation.findings),
            )

            task = self.finalizer.append_evaluation(task, evaluation)
            if evaluation.completed:
                task.result_summary = evaluation.reason
                if evaluation.success:
                    self.events.complete(task.task_id)
                    return self.finalizer.finish_success(task, owns_status)

                self.events.fail(task.task_id, evaluation.reason or "评估判定失败")
                raise TaskError(evaluation.reason or "黑盒任务已完成，但评估结果为失败。")

            if executed_steps >= task_input.max_steps:
                break

            # ── 重新规划 ──
            sequence, _last_error = await self._plan_next(
                task, latest_observation, planner, _last_error
            )

        # ── 达到最大步骤 ──
        return await self._handle_max_steps(task, task_input, owns_status)

    async def _plan_next(
        self,
        task: Task,
        latest_observation: str,
        planner: BlackboxPlanner,
        last_error: dict | None,
    ) -> tuple[ActionSequence, dict | None]:
        """请求规划器生成下一批动作。返回 (sequence, last_error_cleared)。"""
        if task.logs and task.logs[-1].url_after:
            current_url = redact_href(task.logs[-1].url_after)
        else:
            current_url = redact_href(task.start_url or "")

        step = task.current_step + 1
        self.events.planner_start(task.task_id, step, task.goal, current_url)

        result = await planner.plan_next(
            goal=task.goal,
            current_url=current_url,
            page_snapshot=latest_observation,
            history=self.finalizer.history(task),
            max_steps=self.max_plan_steps,
            last_error=last_error,
        )

        self.events.planner_result(task.task_id, step, len(result.steps), result.summary)
        return result, None  # last_error cleared after planning

    async def _check_cancelled(self, task: Task) -> bool:
        """检查任务是否被外部取消或暂停。"""
        if self._check_cancelled_fn is not None:
            return self._check_cancelled_fn(task)

        from argus_py.core.cancellation import CancellationToken

        token: CancellationToken = self.service.get_cancellation_token(task.task_id)
        if token.is_cancelled:
            return True
        if token.is_paused:
            await token.wait_if_paused()
            latest = self.service.get_latest_task(task)
            return latest.status is not TaskStatus.RUNNING
        return False

    async def _handle_max_steps(
        self, task: Task, task_input: BlackboxTaskInput, owns_status: bool
    ) -> Task:
        """达到最大步骤时的收尾处理。"""
        message = f"达到最大步骤 {task_input.max_steps} 后仍未完成目标。"
        latest = self.service.get_latest_task(task)
        if owns_status and latest.status is TaskStatus.RUNNING:
            self.events.max_steps(latest.task_id, message)
            failed = self.service.fail_task(latest, message)
            self.finalizer.generate_report(failed)
        raise TaskError(message)
