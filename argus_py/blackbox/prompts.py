"""黑盒 Prompt 模板入口。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from argus_py.llm.prompts import load_prompt, render_prompt

PLANNER_PROMPT = "blackbox_planner.md"
EVALUATOR_PROMPT = "blackbox_evaluator.md"


def load_planner_prompt() -> str:
    """读取内置 planner prompt。"""
    return load_prompt(PLANNER_PROMPT)


def load_evaluator_prompt() -> str:
    """读取内置 evaluator prompt。"""
    return load_prompt(EVALUATOR_PROMPT)


def render_planner_prompt(**kwargs: Any) -> str:
    """渲染内置 planner prompt 占位符。"""
    return render_prompt(PLANNER_PROMPT, **kwargs)


def render_evaluator_prompt(**kwargs: Any) -> str:
    """渲染内置 evaluator prompt 占位符。"""
    return render_prompt(EVALUATOR_PROMPT, **kwargs)


def _compose(base: str, extensions: Iterable[str]) -> str:
    """把非空扩展按顺序追加到 base 末尾。"""
    parts: list[str] = [base.rstrip()]
    for ext in extensions:
        if ext is None:
            continue
        cleaned = ext.strip()
        if cleaned:
            parts.append(cleaned)
    return "\n\n".join(parts)


def compose_planner_prompt(*extensions: str) -> str:
    """读取内置 planner prompt，按顺序追加非空扩展片段。"""
    return _compose(load_planner_prompt(), extensions)


def compose_evaluator_prompt(*extensions: str) -> str:
    """读取内置 evaluator prompt，按顺序追加非空扩展片段。"""
    return _compose(load_evaluator_prompt(), extensions)
