"""黑盒 Prompt 模板入口。"""

from __future__ import annotations

from argus_py.llm.prompts import load_prompt, render_prompt

PLANNER_PROMPT = "blackbox_planner.md"
EVALUATOR_PROMPT = "blackbox_evaluator.md"


def load_planner_prompt() -> str:
    return load_prompt(PLANNER_PROMPT)


def load_evaluator_prompt() -> str:
    return load_prompt(EVALUATOR_PROMPT)


def render_planner_prompt(**kwargs: object) -> str:
    return render_prompt(PLANNER_PROMPT, **kwargs)


def render_evaluator_prompt(**kwargs: object) -> str:
    return render_prompt(EVALUATOR_PROMPT, **kwargs)
