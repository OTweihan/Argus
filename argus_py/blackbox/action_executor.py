"""浏览器动作执行器。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from argus_py.blackbox.evidence import EvidenceCollector
from argus_py.blackbox.models import ActionStep
from argus_py.browser import BrowserSession
from argus_py.browser.errors import BrowserTimeoutError, ElementNotFoundError
from argus_py.browser.url_validator import validate_url
from argus_py.core.enums import ActionType, StepResult
from argus_py.core.exceptions import TaskError
from argus_py.task.models import Task
from argus_py.task.service import TaskService
from argus_py.utils.jsonx import to_jsonable

logger = logging.getLogger(__name__)


def resolve_error_code(exc: Exception) -> str | None:
    """根据异常类型推断错误码。"""
    if isinstance(exc, TaskError):
        return exc.error_code
    if isinstance(exc, BrowserTimeoutError):
        return "timeout"
    if isinstance(exc, ElementNotFoundError):
        return "element_not_found"
    return None


class ActionExecutor:
    """管理浏览器动作的分发和执行。"""

    def __init__(self, service: TaskService, evidence_collector: EvidenceCollector) -> None:
        self.service = service
        self.evidence = evidence_collector
        self._action_handlers: dict[ActionType, Callable] = {
            ActionType.GOTO: self._goto,
            ActionType.CLICK: self._click,
            ActionType.FILL: self._fill,
            ActionType.PRESS: self._press,
            ActionType.SELECT: self._select,
            ActionType.WAIT: self._wait,
            ActionType.SCREENSHOT: self._screenshot,
            ActionType.SNAPSHOT: self._snapshot,
            ActionType.ASSERT: self._assert_action,
        }

    async def execute_action(
        self,
        task: Task,
        session: BrowserSession,
        step: ActionStep,
    ) -> tuple[Task, str]:
        """执行单个浏览器动作并记录步骤日志。"""
        try:
            result = await self.dispatch_action(task, session, step)
        except Exception as exc:
            screenshot_path, _ = await self.evidence.capture_step_evidence(task, session)
            error_code = resolve_error_code(exc)
            self.service.append_log(
                task,
                action=step.action.value,
                result=StepResult.FAILED,
                params=self._step_params(step),
                screenshot_path=screenshot_path,
                message=step.reason,
                error=str(exc),
                error_code=error_code,
            )
            raise TaskError(
                f"黑盒动作执行失败：{step.action.value}，原因：{exc}", error_code=error_code
            ) from exc

        screenshot_path = result.get("screenshot_path")
        screenshot_path, snapshot = await self.evidence.capture_step_evidence(
            task, session, screenshot_path=screenshot_path
        )
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

    async def dispatch_action(
        self,
        task: Task,
        session: BrowserSession,
        step: ActionStep,
    ) -> dict[str, Any]:
        """分发浏览器动作。"""
        handler = self._action_handlers.get(step.action)
        if handler is None:
            raise TaskError(f"不支持的动作类型：{step.action.value}")
        return await handler(task, session, step)

    async def _goto(self, task: Task, session: BrowserSession, step: ActionStep) -> dict[str, Any]:
        """执行 goto 跳转。"""
        if not step.url:
            raise TaskError("goto 动作缺少 url。", error_code="empty_url")
        validation = validate_url(step.url)
        if not validation.is_ok():
            raise TaskError(
                f"URL 校验失败：{validation.error_message}",
                error_code=validation.code,
            )
        return await session.goto(step.url)

    async def _click(self, task: Task, session: BrowserSession, step: ActionStep) -> dict[str, Any]:
        """执行 click 点击。"""
        if not step.selector:
            raise TaskError("click 动作缺少 selector。", error_code="param_invalid")
        return await session.click(step.selector)

    async def _fill(self, task: Task, session: BrowserSession, step: ActionStep) -> dict[str, Any]:
        """执行 fill 填充。"""
        if not step.selector:
            raise TaskError("fill 动作缺少 selector。", error_code="param_invalid")
        return await session.fill(step.selector, step.text or "")

    async def _press(self, task: Task, session: BrowserSession, step: ActionStep) -> dict[str, Any]:
        """执行 press 按键。"""
        if not step.selector or not step.key:
            raise TaskError("press 动作缺少 selector 或 key。", error_code="param_invalid")
        return await session.require_actions().press(step.selector, step.key)

    async def _select(
        self, task: Task, session: BrowserSession, step: ActionStep
    ) -> dict[str, Any]:
        """执行 select 选择。"""
        if not step.selector:
            raise TaskError("select 动作缺少 selector。", error_code="param_invalid")
        value = step.text or str(step.params.get("value") or "")
        if not value:
            raise TaskError("select 动作缺少选项值。", error_code="param_invalid")
        return await session.require_actions().select_option(step.selector, value)

    async def _wait(self, task: Task, session: BrowserSession, step: ActionStep) -> dict[str, Any]:
        """执行 wait 等待。"""
        return await session.require_actions().wait(step.wait_ms or 1000)

    async def _screenshot(
        self, task: Task, session: BrowserSession, step: ActionStep
    ) -> dict[str, Any]:
        """执行 screenshot 截图。"""
        if not task.capture_screenshots:
            return {"message": "截图已按任务配置跳过。"}
        screenshot_path = await session.screenshot(
            self.evidence.screenshot_name(task), full_page=True
        )
        return {"screenshot_path": str(screenshot_path), "message": "截图已保存。"}

    async def _snapshot(
        self, task: Task, session: BrowserSession, step: ActionStep
    ) -> dict[str, Any]:
        """执行 snapshot 快照。"""
        snapshot = await session.snapshot()
        return {
            "url_after": snapshot.url,
            "message": f"页面快照已获取，可交互元素 {len(snapshot.interactive_elements)} 个。",
        }

    async def _assert_action(
        self, task: Task, session: BrowserSession, step: ActionStep
    ) -> dict[str, Any]:
        """执行 assert 断言。"""
        return {"message": step.reason or "断言交由评估器判断。"}

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
