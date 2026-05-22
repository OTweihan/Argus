from pathlib import Path
from typing import Any

import pytest
from argus_py.blackbox.evaluator import BlackboxEvaluator, EvaluationResult
from argus_py.blackbox.models import ActionSequence, ActionStep, BlackboxTaskInput
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.blackbox.prompts import load_evaluator_prompt, load_planner_prompt
from argus_py.blackbox.runner import BlackboxRunner
from argus_py.core.enums import ActionType, TaskStatus
from argus_py.llm.models import ChatResponse
from argus_py.llm.parser import extract_json
from argus_py.report.generator import ReportGenerator
from argus_py.task.event import _NullTimelineService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.log import TaskLogService
from argus_py.task.read import TaskReadService
from argus_py.task.storage import TaskFileStorage


def test_extract_json_from_markdown_block():
    data = extract_json('```json\n{"action": "screenshot"}\n```')

    assert data["action"] == "screenshot"


def test_blackbox_prompts_require_login_interaction_coverage():
    """冻结 planner / evaluator 内置 Prompt 中与登录、表单、selector 安全相关的关键短语，
    避免在演化 Prompt 时无意中丢失安全契约或测试覆盖语义。
    """
    planner_prompt = load_planner_prompt()
    evaluator_prompt = load_evaluator_prompt()

    assert "登录 / 注册" in planner_prompt
    assert "空表单提交" in planner_prompt
    assert "明显无效账号密码" in planner_prompt
    assert "`selector=` 推荐值" in planner_prompt
    assert "button:contains" in planner_prompt
    assert "不要重复上一步失败的同一 selector" in planner_prompt
    assert "不要继续无限重试同类动作" in planner_prompt
    assert "不能只因为元素存在或页面已打开就完成" in evaluator_prompt
    assert "history 中存在实际交互证据" in evaluator_prompt
    assert "已覆盖的测试场景" in evaluator_prompt
    assert "只观察到必填校验" in evaluator_prompt


class FakeLLMClient:
    def __init__(self, content: str) -> None:
        self.content = content

    async def complete(self, **kwargs) -> ChatResponse:
        return ChatResponse(content=self.content, model="fake")


@pytest.mark.asyncio
async def test_blackbox_planner_parses_llm_actions():
    planner = BlackboxPlanner(
        llm_client=FakeLLMClient("""
            {
              "summary": "点击表单入口",
              "steps": [
                {"action": "click", "selector": "text=HTML Forms", "reason": "进入表单页"}
              ]
            }
            """)
    )

    sequence = await planner.plan_next(
        goal="进入表单页",
        current_url="https://httpbin.org",
        page_snapshot="HTML Forms",
        history=[],
    )

    assert sequence.summary == "点击表单入口"
    assert sequence.steps[0].action is ActionType.CLICK
    assert sequence.steps[0].selector == "text=HTML Forms"


@pytest.mark.asyncio
async def test_blackbox_evaluator_parses_llm_findings():
    evaluator = BlackboxEvaluator(
        llm_client=FakeLLMClient("""
            {
              "completed": true,
              "success": false,
              "reason": "页面出现错误",
              "findings": [
                {
                  "severity": "medium",
                  "type": "error",
                  "title": "页面错误",
                  "description": "页面显示错误信息"
                }
              ]
            }
            """)
    )

    result = await evaluator.evaluate("检查页面", "页面错误", history=[])

    assert result.completed is True
    assert result.success is False
    assert result.findings[0].title == "页面错误"


class FakeSnapshot:
    url = "https://example.com"
    interactive_elements: list[Any] = []

    def to_prompt_text(self) -> str:
        return "URL: https://example.com\nTitle: Example"


class FakeBrowserSession:
    def __init__(self, screenshot_dir: Path) -> None:
        self.screenshot_dir = screenshot_dir

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    async def goto(self, url: str) -> dict:
        return {"url_before": "about:blank", "url_after": url, "title": "Example"}

    async def click(self, target: str) -> dict:
        return {"url_after": "https://example.com", "title": "Example"}

    async def fill(self, target: str, text: str) -> dict:
        return {"url_after": "https://example.com", "title": "Example"}

    async def screenshot(self, name: str, full_page: bool = True) -> Path:
        return self.screenshot_dir / name

    async def snapshot(self) -> FakeSnapshot:
        return FakeSnapshot()


class FakePlanner:
    """不携带 llm_client 的规划器桩，避免 LLMBoundaryFactory 触发 LLM client 解析。"""

    async def plan_initial(self, task_input: BlackboxTaskInput) -> ActionSequence:
        return ActionSequence(
            steps=[
                ActionStep(action=ActionType.GOTO, url=task_input.start_url, reason="打开起始 URL")
            ]
        )

    async def plan_next(
        self,
        goal: str,
        current_url: str,
        page_snapshot: str,
        history: list[dict],
        max_steps: int = 3,
        last_error: dict | None = None,
        evaluator_next_action: str = "",
    ) -> ActionSequence:
        return ActionSequence(steps=[], summary="完成")


class CountingEvaluator:
    def __init__(self) -> None:
        self.count = 0
        self.last_history: list[Any] = []

    async def evaluate(self, goal: str, observation: str, history=None) -> EvaluationResult:
        self.count += 1
        self.last_history = history or []
        return EvaluationResult(
            completed=self.count >= 1,
            success=True,
            reason="初始页面已记录",
        )


@pytest.mark.asyncio
async def test_blackbox_runner_executes_initial_browser_loop(tmp_path):
    storage = TaskFileStorage(tmp_path / "tasks")
    lifecycle = TaskLifecycleService(storage, event_publisher=None)
    reader = TaskReadService(storage)
    log_service = TaskLogService(storage, event_publisher=None)
    timeline = _NullTimelineService()
    task = lifecycle.create_task(goal="打开页面并截图", start_url="https://example.com")
    runner = BlackboxRunner(
        lifecycle=lifecycle,
        reader=reader,
        log_service=log_service,
        timeline_service=timeline,
        planner=FakePlanner(),
        evaluator=CountingEvaluator(),
        browser_session_factory=lambda _: FakeBrowserSession(tmp_path),
        report_generator=ReportGenerator(tmp_path / "reports"),
    )

    completed = await runner.run(task)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.current_step == 1
    assert completed.logs[0].action == "goto"
    assert completed.logs[0].screenshot_path is not None
    # history 记录的是 filename（无路径），logs 是完整路径，只校验文件名一致
    assert (
        runner.evaluator.last_history[0]["screenshot_path"]
        == Path(completed.logs[0].screenshot_path).name
    )
    assert completed.result_summary == "初始页面已记录"
    assert completed.report_path is not None


class RecoveryPlanner:
    def __init__(self) -> None:
        self.plan_next_calls = 0

    async def plan_initial(self, task_input: BlackboxTaskInput) -> ActionSequence:
        return ActionSequence(
            steps=[
                ActionStep(action=ActionType.GOTO, url=task_input.start_url),
                ActionStep(
                    action=ActionType.CLICK, selector="css=.missing", reason="尝试点击登录按钮"
                ),
            ]
        )

    async def plan_next(self, **kwargs) -> ActionSequence:
        self.plan_next_calls += 1
        return ActionSequence(
            steps=[ActionStep(action=ActionType.SCREENSHOT, reason="恢复后记录页面")]
        )


class FailingClickBrowserSession(FakeBrowserSession):
    async def click(self, target: str) -> dict:
        raise RuntimeError(f"页面元素未找到：{target}")


class CompleteEvaluator:
    async def evaluate(self, goal: str, observation: str, history=None) -> EvaluationResult:
        return EvaluationResult(
            completed=True,
            success=True,
            reason="已从失败动作恢复并记录页面。",
        )


@pytest.mark.asyncio
async def test_blackbox_runner_replans_after_action_failure(tmp_path):
    storage = TaskFileStorage(tmp_path / "tasks")
    lifecycle = TaskLifecycleService(storage, event_publisher=None)
    reader = TaskReadService(storage)
    log_service = TaskLogService(storage, event_publisher=None)
    timeline = _NullTimelineService()
    task = lifecycle.create_task(goal="测试登录界面", start_url="https://example.com/login")
    planner = RecoveryPlanner()
    runner = BlackboxRunner(
        lifecycle=lifecycle,
        reader=reader,
        log_service=log_service,
        timeline_service=timeline,
        planner=planner,
        evaluator=CompleteEvaluator(),
        browser_session_factory=lambda _: FailingClickBrowserSession(tmp_path),
        report_generator=ReportGenerator(tmp_path / "reports"),
    )

    completed = await runner.run(task)

    assert completed.status is TaskStatus.COMPLETED
    assert planner.plan_next_calls == 1
    assert [log.result.value for log in completed.logs] == ["success", "failed", "success"]
    assert completed.logs[1].action == "click"
    assert completed.logs[2].action == "screenshot"
    assert completed.logs[0].screenshot_path is not None
    assert completed.logs[1].screenshot_path is not None
    assert completed.logs[2].screenshot_path is not None


class ScreenshotOnlyPlanner:
    async def plan_initial(self, task_input: BlackboxTaskInput) -> ActionSequence:
        return ActionSequence(steps=[ActionStep(action=ActionType.SCREENSHOT, reason="尝试截图")])


@pytest.mark.asyncio
async def test_blackbox_runner_skips_screenshot_when_disabled(tmp_path):
    storage = TaskFileStorage(tmp_path / "tasks")
    lifecycle = TaskLifecycleService(storage, event_publisher=None)
    reader = TaskReadService(storage)
    log_service = TaskLogService(storage, event_publisher=None)
    timeline = _NullTimelineService()
    task = lifecycle.create_task(
        goal="打开页面",
        start_url="https://example.com",
        capture_screenshots=False,
    )
    runner = BlackboxRunner(
        lifecycle=lifecycle,
        reader=reader,
        log_service=log_service,
        timeline_service=timeline,
        planner=ScreenshotOnlyPlanner(),
        evaluator=CompleteEvaluator(),
        browser_session_factory=lambda _: FakeBrowserSession(tmp_path),
        report_generator=ReportGenerator(tmp_path / "reports"),
    )

    completed = await runner.run(task)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.logs[0].action == "screenshot"
    assert completed.logs[0].screenshot_path is None
    assert completed.logs[0].message == "截图已按任务配置跳过。"
