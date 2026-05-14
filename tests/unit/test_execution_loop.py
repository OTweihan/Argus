"""``BlackboxExecutionLoop`` 控制流单测。

聚焦点：

- 规划器返回空 sequence 抛 ``TaskError``
- evaluator 完成 + 成功 → finalize_success
- evaluator 完成 + 失败 → 抛 ``TaskError``
- 动作失败 + RecoveryPolicy.REPLAN → 重新规划
- 动作失败 + RecoveryPolicy.ABORT → 抛 ``TaskError``
- 达到 ``max_steps`` 走 ``_handle_max_steps`` 落 fail_task
- ``_check_cancelled`` 命中 cancel：直接调 finalize 走完结分支

action_executor / planner / evaluator 全部用 stub，避免触达真实 LLM / 浏览器。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from argus_py.blackbox.action_executor import ActionExecutor
from argus_py.blackbox.evaluator import BlackboxEvaluator, EvaluationResult
from argus_py.blackbox.events import BlackboxEvents
from argus_py.blackbox.evidence import EvidenceCollector
from argus_py.blackbox.execution_loop import BlackboxExecutionLoop
from argus_py.blackbox.finalizer import Finalizer
from argus_py.blackbox.models import ActionSequence, ActionStep, BlackboxTaskInput
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.blackbox.recovery import RecoveryPolicy
from argus_py.browser import BrowserSession
from argus_py.core.enums import ActionType, StepResult, TaskStatus
from argus_py.core.exceptions import TaskError
from argus_py.report.generator import ReportGenerator
from argus_py.task.models import Task
from argus_py.task.service import TaskService
from argus_py.task.storage import TaskFileStorage

# ── Stubs ────────────────────────────────────────────────────────────────────


class StubSnapshot:
    url = "https://example.com"
    interactive_elements: list[Any] = []

    def to_prompt_text(self) -> str:
        return "stub-snapshot"


class StubBrowserSession:
    """``BlackboxExecutionLoop`` 内部仅在 evidence.safe_observation 中调 ``snapshot()``。"""

    async def snapshot(self) -> StubSnapshot:
        return StubSnapshot()


class StubPlanner:
    """按预设序列返回 plan_initial / plan_next 的结果。"""

    def __init__(
        self,
        initial: ActionSequence | None = None,
        nexts: list[ActionSequence] | None = None,
    ) -> None:
        self.initial = initial or ActionSequence(steps=[])
        self.nexts = list(nexts or [])
        self.plan_initial_calls = 0
        self.plan_next_calls = 0
        self.last_next_kwargs: dict[str, Any] | None = None

    async def plan_initial(self, task_input: BlackboxTaskInput) -> ActionSequence:
        self.plan_initial_calls += 1
        return self.initial

    async def plan_next(self, **kwargs: Any) -> ActionSequence:
        self.plan_next_calls += 1
        self.last_next_kwargs = kwargs
        if not self.nexts:
            return ActionSequence(steps=[])
        return self.nexts.pop(0)


class StubEvaluator:
    """按队列逐个返回评估结果。"""

    def __init__(self, results: list[EvaluationResult]) -> None:
        self.results = list(results)
        self.calls = 0

    async def evaluate(
        self, goal: str, observation: str, history: list[dict[str, Any]] | None = None
    ) -> EvaluationResult:
        self.calls += 1
        if self.results:
            return self.results.pop(0)
        # 默认未完成，逼迫调用方重新规划
        return EvaluationResult(completed=False, success=False, reason="continue")


class StubActionExecutor:
    """按预设响应序列模拟 ``execute_action`` 行为。

    每个 response 可以是：

    - ``Exception``：直接 raise（execute_action 自然 raise，不会写 log，由 loop 在 except 里走恢复路径）
    - ``("success", url_after, observation)``：写一条 SUCCESS 日志并返回 (new_task, observation)
    - ``("failure_with_log", error_code)``：写一条 FAILED 日志后抛 TaskError（模拟真实 ActionExecutor 内部失败路径）
    """

    def __init__(self, service: TaskService, responses: list[Any]) -> None:
        self.service = service
        self.responses = list(responses)
        self.call_count = 0

    async def execute_action(self, task: Task, session: Any, step: ActionStep) -> tuple[Task, str]:
        self.call_count += 1
        if not self.responses:
            raise AssertionError("StubActionExecutor 收到了超出预设的调用")
        item = self.responses.pop(0)

        if isinstance(item, BaseException):
            raise item

        kind = item[0]
        if kind == "success":
            _, url_after, observation = item
            new_task = self.service.append_log(
                task,
                action=step.action.value,
                result=StepResult.SUCCESS,
                params={},
                url_after=url_after,
                screenshot_path=None,
            )
            return new_task, observation
        if kind == "failure_with_log":
            _, error_code = item
            self.service.append_log(
                task,
                action=step.action.value,
                result=StepResult.FAILED,
                params={},
                error="boom",
                error_code=error_code,
            )
            raise TaskError("boom", error_code=error_code)
        raise AssertionError(f"未知的 stub response: {item!r}")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _action_executor(executor: StubActionExecutor) -> ActionExecutor:
    """测试 stub 只实现 BlackboxExecutionLoop 触达的 ActionExecutor 最小协议。"""
    return cast(ActionExecutor, executor)


def _planner(planner: StubPlanner) -> BlackboxPlanner:
    return cast(BlackboxPlanner, planner)


def _evaluator(evaluator: StubEvaluator) -> BlackboxEvaluator:
    return cast(BlackboxEvaluator, evaluator)


def _browser_session(session: StubBrowserSession) -> BrowserSession:
    return cast(BrowserSession, session)


def _build_loop(
    tmp_path: Path,
    *,
    action_responses: list[Any],
    max_recovery_attempts: int = 2,
    check_cancelled_fn=None,
) -> tuple[BlackboxExecutionLoop, TaskService, StubActionExecutor]:
    service = TaskService(TaskFileStorage(tmp_path / "tasks"))
    executor = StubActionExecutor(service, action_responses)
    finalizer = Finalizer(service, ReportGenerator(tmp_path / "reports"))
    evidence = EvidenceCollector()
    events = BlackboxEvents(service)
    policy = RecoveryPolicy(max_attempts=max_recovery_attempts)
    loop = BlackboxExecutionLoop(
        service=service,
        action_executor=_action_executor(executor),
        finalizer=finalizer,
        evidence=evidence,
        events=events,
        recovery_policy=policy,
        max_plan_steps=3,
        check_cancelled_fn=check_cancelled_fn,
    )
    return loop, service, executor


def _start_task(service: TaskService, **overrides: Any) -> Task:
    task = service.create_task(
        goal=overrides.pop("goal", "g"),
        start_url=overrides.pop("start_url", "https://example.com"),
        max_steps=overrides.pop("max_steps", 5),
        capture_screenshots=overrides.pop("capture_screenshots", False),
    )
    return service.start_task(task)


def _input(task: Task) -> BlackboxTaskInput:
    return BlackboxTaskInput(
        goal=task.goal,
        start_url=task.start_url or "",
        max_steps=task.max_steps,
        timeout_seconds=task.timeout_seconds,
        capture_screenshots=task.capture_screenshots,
    )


# ── 测试 ─────────────────────────────────────────────────────────────────────


async def test_initial_plan_empty_raises_task_error(tmp_path: Path) -> None:
    """plan_initial 返回空 sequence → 抛 ``规划器未返回可执行动作。``"""
    loop, service, _ = _build_loop(tmp_path, action_responses=[])
    task = _start_task(service)
    planner = StubPlanner(initial=ActionSequence(steps=[]))
    evaluator = StubEvaluator(results=[])

    with pytest.raises(TaskError, match="规划器未返回可执行动作"):
        await loop.run(
            task,
            _input(task),
            _planner(planner),
            _evaluator(evaluator),
            _browser_session(StubBrowserSession()),
            owns_status=True,
        )


async def test_single_step_then_evaluator_success_completes_task(tmp_path: Path) -> None:
    """一次成功执行 + evaluator(completed, success) → 任务进入 COMPLETED。"""
    loop, service, executor = _build_loop(
        tmp_path,
        action_responses=[("success", "https://example.com/after", "obs-1")],
    )
    task = _start_task(service)
    planner = StubPlanner(
        initial=ActionSequence(
            steps=[ActionStep(action=ActionType.GOTO, url="https://example.com")],
            summary="open",
        )
    )
    evaluator = StubEvaluator(
        results=[EvaluationResult(completed=True, success=True, reason="done")]
    )

    completed = await loop.run(
        task,
        _input(task),
        _planner(planner),
        _evaluator(evaluator),
        _browser_session(StubBrowserSession()),
        owns_status=True,
    )

    assert completed.status is TaskStatus.COMPLETED
    assert executor.call_count == 1
    assert completed.result_summary == "done"
    # plan_next 不应被调用
    assert planner.plan_next_calls == 0


async def test_evaluator_completed_but_failed_raises_task_error(tmp_path: Path) -> None:
    """evaluator(completed=True, success=False) → 抛 ``TaskError`` + 不会标记完成。"""
    loop, service, _ = _build_loop(
        tmp_path,
        action_responses=[("success", "https://example.com/after", "obs-1")],
    )
    task = _start_task(service)
    planner = StubPlanner(
        initial=ActionSequence(
            steps=[ActionStep(action=ActionType.GOTO, url="https://example.com")]
        )
    )
    evaluator = StubEvaluator(
        results=[EvaluationResult(completed=True, success=False, reason="fail-reason")]
    )

    with pytest.raises(TaskError, match="fail-reason"):
        await loop.run(
            task,
            _input(task),
            _planner(planner),
            _evaluator(evaluator),
            _browser_session(StubBrowserSession()),
            owns_status=True,
        )


async def test_replan_error_code_triggers_replan_without_consuming_attempts(
    tmp_path: Path,
) -> None:
    """``param_invalid`` 命中 ``RecoveryPolicy.REPLAN`` → 触发 plan_next 而非中止。"""
    loop, service, executor = _build_loop(
        tmp_path,
        action_responses=[
            ("failure_with_log", "param_invalid"),  # 第 1 次执行 click 失败
            ("success", "https://example.com/after", "obs-1"),  # 重新规划后成功
        ],
        max_recovery_attempts=2,
    )
    task = _start_task(service)
    planner = StubPlanner(
        initial=ActionSequence(steps=[ActionStep(action=ActionType.CLICK, selector="#x")]),
        nexts=[
            ActionSequence(steps=[ActionStep(action=ActionType.GOTO, url="https://example.com")])
        ],
    )
    evaluator = StubEvaluator(
        results=[EvaluationResult(completed=True, success=True, reason="recovered")]
    )

    completed = await loop.run(
        task,
        _input(task),
        _planner(planner),
        _evaluator(evaluator),
        _browser_session(StubBrowserSession()),
        owns_status=True,
    )

    assert completed.status is TaskStatus.COMPLETED
    # plan_next 被触发了一次（恢复路径）
    assert planner.plan_next_calls == 1
    # 两次 action 调用：失败 + 恢复成功
    assert executor.call_count == 2
    # last_error 在重新规划成功后应被清空（loop._plan_next 返回 None）
    assert planner.last_next_kwargs is not None
    # ``StubActionExecutor`` 直接 raise TaskError("boom")，所以 last_error.error_message
    # 就是 "boom"。真实 ``ActionExecutor`` 会包装成 "黑盒动作执行失败：click，原因：boom"，
    # 但 loop 自身只把 ``str(exc)`` 透传到 last_error，文案由上游决定，本测试只契约结构。
    assert planner.last_next_kwargs["last_error"] == {
        "action": "click",
        "error_code": "param_invalid",
        "error_message": "boom",
        "step_number": 1,
    }


async def test_recovery_attempts_exhausted_aborts(tmp_path: Path) -> None:
    """普通错误码达到 ``max_attempts`` 时直接 ABORT，向外抛出 ``TaskError``。"""
    loop, service, _ = _build_loop(
        tmp_path,
        action_responses=[
            ("failure_with_log", "transient"),
            ("failure_with_log", "transient"),
            ("failure_with_log", "transient"),
        ],
        max_recovery_attempts=2,
    )
    task = _start_task(service)
    planner = StubPlanner(
        initial=ActionSequence(steps=[ActionStep(action=ActionType.CLICK, selector="#x")]),
        # plan_next 一直返回相同失败动作，迫使 RETRY 计数累加
        nexts=[
            ActionSequence(steps=[ActionStep(action=ActionType.CLICK, selector="#x")]),
            ActionSequence(steps=[ActionStep(action=ActionType.CLICK, selector="#x")]),
        ],
    )
    evaluator = StubEvaluator(results=[])

    with pytest.raises(TaskError):
        await loop.run(
            task,
            _input(task),
            _planner(planner),
            _evaluator(evaluator),
            _browser_session(StubBrowserSession()),
            owns_status=True,
        )


async def test_max_steps_reached_fails_task_and_raises(tmp_path: Path) -> None:
    """步骤数达到 ``max_steps`` → ``_handle_max_steps`` 调用 fail_task 并抛错。"""
    loop, service, _ = _build_loop(
        tmp_path,
        action_responses=[
            ("success", "https://example.com/a", "obs-1"),
            ("success", "https://example.com/b", "obs-2"),
        ],
    )
    task = _start_task(service, max_steps=2)
    planner = StubPlanner(
        initial=ActionSequence(
            steps=[
                ActionStep(action=ActionType.GOTO, url="https://example.com/a"),
                ActionStep(action=ActionType.GOTO, url="https://example.com/b"),
            ]
        ),
        nexts=[],
    )
    # evaluator 始终返回 completed=False，迫使 loop 走到 max_steps
    evaluator = StubEvaluator(
        results=[
            EvaluationResult(completed=False, success=False, reason="r1"),
            EvaluationResult(completed=False, success=False, reason="r2"),
        ]
    )

    with pytest.raises(TaskError, match="达到最大步骤"):
        await loop.run(
            task,
            _input(task),
            _planner(planner),
            _evaluator(evaluator),
            _browser_session(StubBrowserSession()),
            owns_status=True,
        )

    latest = service.get_task(task.task_id)
    assert latest.status is TaskStatus.FAILED


async def test_check_cancelled_short_circuits_to_finalize(tmp_path: Path) -> None:
    """``check_cancelled_fn`` 返回 True 时直接 finalize，不会执行任何动作。"""
    loop, service, executor = _build_loop(
        tmp_path,
        action_responses=[],
        check_cancelled_fn=lambda task: True,
    )
    task = _start_task(service)
    # 强制把 status 改为 CANCELLED 以触发 Finalizer.finalize 的 generate_report 分支
    task = service.cancel_task(task)
    planner = StubPlanner(
        initial=ActionSequence(
            steps=[ActionStep(action=ActionType.GOTO, url="https://example.com")]
        )
    )
    evaluator = StubEvaluator(results=[])

    finalized = await loop.run(
        task,
        _input(task),
        _planner(planner),
        _evaluator(evaluator),
        _browser_session(StubBrowserSession()),
        owns_status=True,
    )

    assert finalized.status is TaskStatus.CANCELLED
    # 关键断言：在 cancel 前置状态下 action_executor 完全没被调用过
    assert executor.call_count == 0
    # plan_initial 也不该被调用（_check_cancelled 命中后立即 return）
    assert planner.plan_initial_calls == 0
