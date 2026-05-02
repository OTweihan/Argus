"""黑盒 Agent 执行器。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from argus_py.blackbox.evaluator import BlackboxEvaluator, EvaluationResult
from argus_py.blackbox.models import ActionSequence, ActionStep, BlackboxTaskInput
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.browser import BrowserSession, PageSnapshot
from argus_py.config.service import resolve_llm_client_for_task
from argus_py.core.enums import ActionType, FindingSeverity, FindingType, StepResult, TaskStatus
from argus_py.core.exceptions import TaskError
from argus_py.core.paths import SCREENSHOTS_DIR
from argus_py.report.generator import ReportGenerator, generate_report_safely
from argus_py.task.models import Task
from argus_py.task.service import TaskService
from argus_py.utils.jsonx import to_jsonable

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
        self.report_generator = report_generator or ReportGenerator()
        self.max_plan_steps = max_plan_steps
        self.max_recovery_attempts = max_recovery_attempts

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
                    if not sequence.steps:
                        sequence = await self._plan_next(resolved, latest_observation, planner)
                        if not sequence.steps:
                            raise TaskError("规划器未返回可执行动作。")

                    for action_step in sequence.steps:
                        if executed_steps >= task_input.max_steps:
                            break
                        executed_steps += 1

                        try:
                            resolved, latest_observation = await self._execute_action(resolved, session, action_step)
                            recovery_attempts = 0
                        except TaskError:
                            if recovery_attempts >= self.max_recovery_attempts:
                                raise
                            recovery_attempts += 1
                            latest_observation = await self._safe_observation(session)
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
                        history=self._history(resolved),
                    )
                    resolved = self._append_evaluation(resolved, evaluation)
                    if evaluation.completed:
                        resolved.result_summary = evaluation.reason
                        if evaluation.success:
                            return self._finish_success(resolved, owns_status)
                        raise TaskError(evaluation.reason or "黑盒任务已完成，但评估结果为失败。")

                    if executed_steps >= task_input.max_steps:
                        break
                    sequence = await self._plan_next(resolved, latest_observation, planner)
        except Exception as exc:
            if owns_status and resolved.status is TaskStatus.RUNNING:
                failed = self.service.fail_task(self._latest_task(resolved), str(exc))
                self._generate_report(failed)
            raise

        message = f"达到最大步骤 {task_input.max_steps} 后仍未完成目标。"
        if owns_status and resolved.status is TaskStatus.RUNNING:
            failed = self.service.fail_task(resolved, message)
            self._generate_report(failed)
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
        """请求规划器生成下一批动作。"""
        if task.logs and task.logs[-1].url_after:
            current_url = task.logs[-1].url_after
        else:
            current_url = task.start_url or ""
        return await planner.plan_next(
            goal=task.goal,
            current_url=current_url,
            page_snapshot=latest_observation,
            history=self._history(task),
            max_steps=self.max_plan_steps,
        )

    def _resolve_llm_boundaries(self, task: Task) -> tuple[BlackboxPlanner, BlackboxEvaluator]:
        """为当前任务解析 LLM 边界，默认实现按模型配置创建独立客户端。"""
        if not self._uses_default_planner and not self._uses_default_evaluator:
            return self.planner, self.evaluator
        llm_client = resolve_llm_client_for_task(task)
        planner = self.planner if not self._uses_default_planner else BlackboxPlanner(llm_client=llm_client)
        evaluator = (
            self.evaluator
            if not self._uses_default_evaluator
            else BlackboxEvaluator(llm_client=llm_client)
        )
        return planner, evaluator

    async def _execute_action(
        self,
        task: Task,
        session: BrowserSession,
        step: ActionStep,
    ) -> tuple[Task, str]:
        """执行单个浏览器动作并记录步骤日志。"""
        try:
            result = await self._dispatch_action(task, session, step)
        except Exception as exc:
            screenshot_path, _ = await self._capture_step_evidence(task, session)
            self.service.append_log(
                task,
                action=step.action.value,
                result=StepResult.FAILED,
                params=self._step_params(step),
                screenshot_path=screenshot_path,
                message=step.reason,
                error=str(exc),
            )
            raise TaskError(f"黑盒动作执行失败：{step.action.value}，原因：{exc}") from exc

        screenshot_path = result.get("screenshot_path")
        screenshot_path, snapshot = await self._capture_step_evidence(task, session, screenshot_path=screenshot_path)
        observation = snapshot.to_prompt_text() if snapshot is not None else ""

        return (
            self.service.append_log(
                task,
                action=step.action.value,
                result=StepResult.SUCCESS,
                params=self._step_params(step),
                url_before=result.get("url_before"),
                url_after=result.get("url_after"),
                screenshot_path=screenshot_path,
                message=self._step_message(step, result),
            ),
            observation,
        )

    async def _dispatch_action(
        self,
        task: Task,
        session: BrowserSession,
        step: ActionStep,
    ) -> dict[str, Any]:
        """分发浏览器动作。"""
        if step.action is ActionType.GOTO:
            if not step.url:
                raise TaskError("goto 动作缺少 url。")
            return await session.goto(step.url)

        if step.action is ActionType.CLICK:
            if not step.selector:
                raise TaskError("click 动作缺少 selector。")
            return await session.click(step.selector)

        if step.action is ActionType.FILL:
            if not step.selector:
                raise TaskError("fill 动作缺少 selector。")
            return await session.fill(step.selector, step.text or "")

        if step.action is ActionType.PRESS:
            if not step.selector or not step.key:
                raise TaskError("press 动作缺少 selector 或 key。")
            return await session.require_actions().press(step.selector, step.key)

        if step.action is ActionType.SELECT:
            if not step.selector:
                raise TaskError("select 动作缺少 selector。")
            value = step.text or str(step.params.get("value") or "")
            if not value:
                raise TaskError("select 动作缺少选项值。")
            return await session.require_actions().select_option(step.selector, value)

        if step.action is ActionType.WAIT:
            return await session.require_actions().wait(step.wait_ms or 1000)

        if step.action is ActionType.SCREENSHOT:
            if not task.capture_screenshots:
                return {"message": "截图已按任务配置跳过。"}
            screenshot_path = await session.screenshot(self._screenshot_name(task), full_page=True)
            return {"screenshot_path": str(screenshot_path), "message": "截图已保存。"}

        if step.action is ActionType.SNAPSHOT:
            snapshot = await session.snapshot()
            return {
                "url_after": snapshot.url,
                "message": f"页面快照已获取，可交互元素 {len(snapshot.interactive_elements)} 个。",
            }

        if step.action is ActionType.ASSERT:
            return {"message": step.reason or "断言交由评估器判断。"}

        raise TaskError(f"不支持的动作类型：{step.action.value}")

    async def _safe_observation(self, session: BrowserSession) -> str:
        """动作失败后尽量获取页面观察，失败时返回可读说明。"""
        try:
            snapshot = await session.snapshot()
            return snapshot.to_prompt_text()
        except Exception as exc:
            return f"页面观察失败：{exc}"

    async def _capture_step_evidence(
        self,
        task: Task,
        session: BrowserSession,
        screenshot_path: str | None = None,
    ) -> tuple[str | None, PageSnapshot | None]:
        """为当前步骤采集截图和页面快照，失败不阻断动作结果。"""
        captured_path = screenshot_path
        if task.capture_screenshots and not captured_path:
            try:
                captured = await session.screenshot(self._screenshot_name(task), full_page=True)
                captured_path = str(captured)
            except Exception:
                captured_path = None

        try:
            return captured_path, await session.snapshot()
        except Exception:
            return captured_path, None

    def _append_evaluation(self, task: Task, evaluation: EvaluationResult) -> Task:
        """把评估器发现的问题写回任务。"""
        resolved = task
        for finding in evaluation.findings:
            resolved = self.service.append_finding(
                resolved,
                title=finding.title,
                description=finding.description,
                severity=finding.severity,
                finding_type=finding.finding_type,
                url=finding.url,
                location=finding.location,
                screenshot_path=finding.screenshot_path,
            )
        if evaluation.completed and not evaluation.success and not evaluation.findings:
            resolved = self.service.append_finding(
                resolved,
                title="黑盒任务失败",
                description=evaluation.reason or "评估器判定目标未成功。",
                severity=FindingSeverity.MEDIUM,
                finding_type=FindingType.FUNCTIONAL,
            )
        return resolved

    def _finish_success(self, task: Task, owns_status: bool) -> Task:
        """按调用方式完成任务。"""
        if owns_status and task.status is TaskStatus.RUNNING:
            completed = self.service.complete_task(task, result_summary=task.result_summary)
            return self._generate_report(completed)
        return self.service.save_task(task)

    def _generate_report(self, task: Task) -> Task:
        """生成任务报告并回写 HTML 报告路径。"""
        return generate_report_safely(task, self.report_generator, self.service.save_task)

    def _latest_task(self, task: Task) -> Task:
        """从存储中读取最新任务快照。"""
        try:
            return self.service.get_task(task.task_id)
        except TaskError:
            return task

    def _history(self, task: Task) -> list[dict[str, Any]]:
        """生成给 LLM 使用的紧凑历史。"""
        return [
            {
                "step_number": log.step_number,
                "action": log.action,
                "result": log.result.value,
                "params": log.params,
                "url_before": log.url_before,
                "url_after": log.url_after,
                "screenshot_path": log.screenshot_path,
                "message": log.message,
                "error": log.error,
            }
            for log in task.logs
        ]

    def _step_params(self, step: ActionStep) -> dict[str, Any]:
        """提取动作参数用于日志。"""
        return to_jsonable(
            {
                "selector": step.selector,
                "url": step.url,
                "text": step.text,
                "key": step.key,
                "wait_ms": step.wait_ms,
                **step.params,
            }
        )

    def _step_message(self, step: ActionStep, result: dict[str, Any]) -> str | None:
        """生成步骤日志说明。"""
        if step.action is ActionType.SCREENSHOT and result.get("message"):
            return str(result["message"])
        return step.reason or result.get("message")

    def _screenshot_name(self, task: Task) -> str:
        """生成步骤截图文件名。"""
        return f"{task.task_id}-step-{task.current_step + 1:03d}.png"

    def _default_browser_session(self, task: Task) -> BrowserSession:
        """创建默认浏览器会话。"""
        screenshot_dir: Path = SCREENSHOTS_DIR / task.task_id
        return BrowserSession(screenshot_dir=screenshot_dir)
