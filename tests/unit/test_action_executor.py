"""``ActionExecutor`` 单测：动作分发、参数校验、错误码映射、execute_action 失败兜底。

为保持轻量，所有外部依赖均用 duck-typed fake：

- ``FakeBrowserSession`` 模拟 ``BrowserSession`` 在测试场景下需要的最小子集
- ``FakeBrowserActions`` 模拟 ``session.require_actions()`` 返回的对象
- ``EvidenceCollector`` 直接复用真实实现（其内部对失败完全静默）
- ``TaskService`` + ``TaskFileStorage`` 走真实文件后端，验证 step 日志确实落到任务上

不依赖 Playwright / 网络，纯本地。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from argus_py.blackbox.action_executor import ActionExecutor, resolve_error_code
from argus_py.blackbox.evidence import EvidenceCollector
from argus_py.blackbox.models import ActionStep
from argus_py.browser import BrowserSession
from argus_py.browser.errors import (
    BrowserActionError,
    BrowserTimeoutError,
    ElementNotFoundError,
)
from argus_py.core.enums import ActionType, StepResult
from argus_py.core.exceptions import TaskError
from argus_py.task.log import TaskLogService
from argus_py.task.service import TaskService
from argus_py.task.storage import TaskFileStorage

# ── Fakes ────────────────────────────────────────────────────────────────────


class FakeSnapshot:
    url = "https://example.com/after"
    interactive_elements: list[Any] = []

    def to_prompt_text(self) -> str:
        return "fake-snapshot"


class FakeBrowserActions:
    """模拟 ``session.require_actions()`` 返回的对象。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    async def press(self, target: str, key: str) -> dict[str, Any]:
        self.calls.append(("press", (target, key), {}))
        return {"url_after": "https://example.com", "title": "Example"}

    async def select_option(self, target: str, value: str) -> dict[str, Any]:
        self.calls.append(("select_option", (target, value), {}))
        return {"url_after": "https://example.com", "title": "Example"}

    async def wait(self, milliseconds: int) -> dict[str, Any]:
        self.calls.append(("wait", (milliseconds,), {}))
        return {"url_after": "https://example.com", "title": "Example"}


class FakeBrowserSession:
    """duck-typed 浏览器会话；所有方法默认返回成功路径。"""

    def __init__(self, screenshot_dir: Path) -> None:
        self.screenshot_dir = screenshot_dir
        self._actions = FakeBrowserActions()
        self.calls: list[tuple[str, tuple, dict]] = []

    def require_actions(self) -> FakeBrowserActions:
        return self._actions

    async def goto(self, url: str) -> dict[str, Any]:
        self.calls.append(("goto", (url,), {}))
        return {"url_before": "about:blank", "url_after": url, "title": "Example"}

    async def click(self, target: str) -> dict[str, Any]:
        self.calls.append(("click", (target,), {}))
        return {"url_after": "https://example.com", "title": "Example"}

    async def fill(self, target: str, text: str) -> dict[str, Any]:
        self.calls.append(("fill", (target, text), {}))
        return {"url_after": "https://example.com", "title": "Example"}

    async def screenshot(self, name: str, full_page: bool = True) -> Path:
        self.calls.append(("screenshot", (name,), {"full_page": full_page}))
        return self.screenshot_dir / name

    async def snapshot(self) -> FakeSnapshot:
        return FakeSnapshot()


class FailingClickSession(FakeBrowserSession):
    async def click(self, target: str) -> dict[str, Any]:
        raise ElementNotFoundError(target)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _browser_session(session: FakeBrowserSession) -> BrowserSession:
    """测试 fake 只实现 ActionExecutor 触达的 BrowserSession 最小协议。"""
    return cast(BrowserSession, session)


def _build_executor(tmp_path: Path) -> tuple[ActionExecutor, TaskService]:
    service = TaskService(TaskFileStorage(tmp_path / "tasks"))
    log_service = TaskLogService(TaskFileStorage(tmp_path / "tasks"))
    executor = ActionExecutor(log_service=log_service, evidence_collector=EvidenceCollector())
    return executor, service


# ── resolve_error_code ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (TaskError("x", error_code="param_invalid"), "param_invalid"),
        (TaskError("x"), None),
        (BrowserTimeoutError("超时"), "timeout"),
        (ElementNotFoundError("button"), "element_not_found"),
        (BrowserActionError("click", "boom", "btn"), None),
        (RuntimeError("other"), None),
    ],
)
def test_resolve_error_code(exc: Exception, expected: str | None) -> None:
    assert resolve_error_code(exc) == expected


# ── 参数校验 / dispatch 错误路径 ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("step", "expected_code"),
    [
        (ActionStep(action=ActionType.GOTO), "empty_url"),
        (ActionStep(action=ActionType.GOTO, url="not a url"), "plain_text"),
        (ActionStep(action=ActionType.CLICK), "param_invalid"),
        (ActionStep(action=ActionType.FILL), "param_invalid"),
        (ActionStep(action=ActionType.PRESS, selector="#a"), "param_invalid"),
        (ActionStep(action=ActionType.PRESS, key="Enter"), "param_invalid"),
        (ActionStep(action=ActionType.SELECT), "param_invalid"),
        (ActionStep(action=ActionType.SELECT, selector="#a"), "param_invalid"),
    ],
    ids=[
        "goto-no-url",
        "goto-plain-text",
        "click-no-selector",
        "fill-no-selector",
        "press-no-key",
        "press-no-selector",
        "select-no-selector",
        "select-no-value",
    ],
)
async def test_dispatch_action_validation_errors(
    tmp_path: Path, step: ActionStep, expected_code: str
) -> None:
    """各 handler 缺参数时直接抛 ``TaskError`` 携带预期 error_code。"""
    executor, service = _build_executor(tmp_path)
    task = service.create_task(goal="g", start_url="https://example.com")
    session = FakeBrowserSession(tmp_path)

    with pytest.raises(TaskError) as exc_info:
        await executor.dispatch_action(task, _browser_session(session), step)

    assert exc_info.value.error_code == expected_code


async def test_dispatch_action_unsupported_type(tmp_path: Path) -> None:
    """未注册的 action 类型抛 TaskError（不带 error_code）。"""
    executor, service = _build_executor(tmp_path)
    task = service.create_task(goal="g", start_url="https://example.com")
    session = FakeBrowserSession(tmp_path)

    # 用一个不在 _action_handlers 字典里的值伪造 step.action
    step = ActionStep(action=ActionType.GOTO, url="https://example.com")
    executor._action_handlers.pop(ActionType.GOTO)

    with pytest.raises(TaskError, match="不支持的动作类型"):
        await executor.dispatch_action(task, _browser_session(session), step)


# ── execute_action：成功路径 ─────────────────────────────────────────────────


async def test_execute_action_success_appends_log(tmp_path: Path) -> None:
    """成功执行后在任务日志中追加 ``StepResult.SUCCESS`` 记录。"""
    executor, service = _build_executor(tmp_path)
    task = service.create_task(goal="g", start_url="https://example.com")
    session = FakeBrowserSession(tmp_path)
    step = ActionStep(action=ActionType.GOTO, url="https://example.com", reason="open page")

    new_task, observation = await executor.execute_action(task, _browser_session(session), step)

    assert observation == "fake-snapshot"
    assert len(new_task.logs) == 1
    log = new_task.logs[0]
    assert log.action == "goto"
    assert log.result is StepResult.SUCCESS
    assert log.url_after == "https://example.com"
    # screenshot_path 由 EvidenceCollector 在成功路径填充（task.capture_screenshots 默认 True）
    assert log.screenshot_path is not None


async def test_execute_action_screenshot_skipped_when_disabled(tmp_path: Path) -> None:
    """task.capture_screenshots=False 时 _screenshot 直接返回跳过消息。"""
    executor, service = _build_executor(tmp_path)
    task = service.create_task(goal="g", start_url="https://example.com", capture_screenshots=False)
    session = FakeBrowserSession(tmp_path)
    step = ActionStep(action=ActionType.SCREENSHOT, reason="snap")

    new_task, _ = await executor.execute_action(task, _browser_session(session), step)

    assert new_task.logs[0].action == "screenshot"
    assert new_task.logs[0].screenshot_path is None
    assert new_task.logs[0].message == "截图已按任务配置跳过。"


# ── execute_action：失败路径 ─────────────────────────────────────────────────


async def test_execute_action_failure_logs_and_raises_with_error_code(tmp_path: Path) -> None:
    """动作内部异常 → 写 FAILED 日志，并抛 TaskError 带映射后的 error_code。"""
    executor, service = _build_executor(tmp_path)
    task = service.create_task(goal="g", start_url="https://example.com")
    session = FailingClickSession(tmp_path)
    step = ActionStep(action=ActionType.CLICK, selector="#missing", reason="点击")

    with pytest.raises(TaskError) as exc_info:
        await executor.execute_action(task, _browser_session(session), step)

    assert exc_info.value.error_code == "element_not_found"
    # 失败路径写入了 FAILED 日志并填了 error_code
    latest = service.get_task(task.task_id)
    assert len(latest.logs) == 1
    assert latest.logs[0].result is StepResult.FAILED
    assert latest.logs[0].error_code == "element_not_found"
    assert latest.logs[0].action == "click"


# ── _step_params 序列化 ────────────────────────────────────────────────────


def test_step_params_serialization_includes_extra_params(tmp_path: Path) -> None:
    """``_step_params`` 把 step 主字段 + ``params`` 字典合并为可 JSON 化的扁平 dict。"""
    executor, _ = _build_executor(tmp_path)
    step = ActionStep(
        action=ActionType.SELECT,
        selector="#country",
        text="CN",
        params={"value": "CN", "extra": 1},
    )
    payload = executor._step_params(step)

    assert payload["selector"] == "#country"
    assert payload["text"] == "CN"
    assert payload["value"] == "CN"
    assert payload["extra"] == 1
