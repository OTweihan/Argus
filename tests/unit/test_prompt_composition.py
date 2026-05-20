"""验证 compose_planner_prompt / compose_evaluator_prompt 的拼接顺序与空值处理。"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from argus_py.blackbox import prompts as prompts_module
from argus_py.blackbox.evaluator import BlackboxEvaluator
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.blackbox.prompts import (
    PROMPT_EXTENSION_MARKER,
    _compose,
    compose_evaluator_prompt,
    compose_planner_prompt,
    load_evaluator_prompt,
    load_planner_prompt,
)
from argus_py.llm.models import ChatResponse


class _CaptureLLMClient:
    """记录最近一次 complete 调用收到的 system_prompt。"""

    def __init__(self, content: str) -> None:
        self.content = content
        self.last_system_prompt: str | None = None

    async def complete(self, **kwargs: Any) -> ChatResponse:
        self.last_system_prompt = kwargs.get("system_prompt")
        return ChatResponse(content=self.content, model="fake")


def test_compose_planner_without_extensions_equals_builtin():
    base = load_planner_prompt()
    composed = compose_planner_prompt()

    assert composed.rstrip() == base.rstrip()


def test_compose_evaluator_without_extensions_equals_builtin():
    base = load_evaluator_prompt()
    composed = compose_evaluator_prompt()

    assert composed.rstrip() == base.rstrip()


def test_compose_planner_appends_single_extension():
    base = load_planner_prompt()
    extension = "## 项目特定规则\n- 危险按钮关键词：作废、出库"

    composed = compose_planner_prompt(extension)

    assert composed.startswith(base.rstrip())
    assert composed.endswith(extension.strip())
    assert composed.index("## 业务扩展") < composed.index("项目特定规则")


def test_compose_planner_preserves_extension_order():
    project_ext = "PROJECT_EXTENSION_MARKER"
    task_ext = "TASK_EXTENSION_MARKER"

    composed = compose_planner_prompt(project_ext, task_ext)

    assert composed.index(project_ext) < composed.index(task_ext)


def test_compose_planner_skips_empty_and_whitespace_extensions():
    base_only = compose_planner_prompt()
    composed = compose_planner_prompt("", "   ", "\n\t  \n", None)

    assert composed == base_only


def test_compose_evaluator_appends_extension_at_tail():
    extension = "EVAL_EXTENSION_UNIQUE_TOKEN"

    composed = compose_evaluator_prompt(extension)

    assert composed.rstrip().endswith(extension)


def test_compose_warns_when_marker_missing(caplog: pytest.LogCaptureFixture) -> None:
    """模板缺 marker 时应 warn 并降级为末尾追加，不静默失语义。"""
    caplog.set_level(logging.WARNING, logger=prompts_module.__name__)

    base_without_marker = "# 内置模板\n\n仅安全边界，没有业务扩展 marker。\n"
    composed = _compose(base_without_marker, ["EXT_TOKEN"], prompt_name="test.md")

    # 行为：扩展仍被追加到末尾（向后兼容）
    assert composed.rstrip().endswith("EXT_TOKEN")
    # 但必须出现 warn，提示模板可能被改坏
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(PROMPT_EXTENSION_MARKER in r.getMessage() for r in warnings)
    assert any("test.md" in r.getMessage() for r in warnings)


def test_compose_no_warn_when_no_extensions(caplog: pytest.LogCaptureFixture) -> None:
    """没有任何扩展时即使 marker 缺失也不应 warn（不会出错也不需要噪声）。"""
    caplog.set_level(logging.WARNING, logger=prompts_module.__name__)
    _compose("没有 marker 的模板。", [], prompt_name="test.md")
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == []


@pytest.mark.asyncio
async def test_planner_passes_composed_system_prompt_to_llm():
    fake_client = _CaptureLLMClient(
        '{"summary": "noop", "steps": [{"action": "screenshot", "reason": "调试"}]}'
    )
    planner = BlackboxPlanner(
        llm_client=fake_client,
        prompt_extensions=["PLANNER_EXTENSION_MARKER_A", "PLANNER_EXTENSION_MARKER_B"],
    )

    await planner.plan_next(
        goal="测试扩展",
        current_url="https://example.com",
        page_snapshot="URL: https://example.com",
        history=[],
    )

    assert fake_client.last_system_prompt is not None
    sys_prompt = fake_client.last_system_prompt
    assert "PLANNER_EXTENSION_MARKER_A" in sys_prompt
    assert "PLANNER_EXTENSION_MARKER_B" in sys_prompt
    assert sys_prompt.index("PLANNER_EXTENSION_MARKER_A") < sys_prompt.index(
        "PLANNER_EXTENSION_MARKER_B"
    )


@pytest.mark.asyncio
async def test_evaluator_passes_composed_system_prompt_to_llm():
    fake_client = _CaptureLLMClient('{"completed": true, "success": true, "reason": "ok"}')
    evaluator = BlackboxEvaluator(
        llm_client=fake_client,
        prompt_extensions=["EVAL_EXTENSION_TOKEN"],
    )

    await evaluator.evaluate(
        goal="测试评估扩展",
        observation="URL: https://example.com",
        history=[],
    )

    assert fake_client.last_system_prompt is not None
    assert "EVAL_EXTENSION_TOKEN" in fake_client.last_system_prompt
