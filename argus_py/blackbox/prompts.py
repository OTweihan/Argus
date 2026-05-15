"""黑盒 Prompt 模板入口。"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from argus_py.llm.prompts import load_prompt, render_prompt

logger = logging.getLogger(__name__)

PLANNER_PROMPT = "blackbox_planner.md"
EVALUATOR_PROMPT = "blackbox_evaluator.md"

# P1-8：内置 Prompt 模板里"业务扩展"区块的 marker。
#
# 调用方扩展（project + task）必须出现在该 marker **之后**（语义：扩展属于
# 业务规则区，不能污染上方的"安全边界"区）。当前模板设计中 marker 始终位于
# 文件末尾，因此"追加到 marker 区块尾" === "追加到文件末尾"。
#
# 这里集中校验 marker 是否存在：缺失说明模板被人改坏（误删 marker 或顺序错了），
# 应警告而不是悄悄把扩展粘到一个没有边界的位置。
PROMPT_EXTENSION_MARKER = "## 业务扩展"


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


def _compose(base: str, extensions: Iterable[str], *, prompt_name: str = "<inline>") -> str:
    """把非空扩展按顺序追加到 ``## 业务扩展`` marker 区块之后。

    当前模板设计中 marker 始终在文件末尾，因此实现等价于"末尾追加"；但显式
    校验 marker 存在能在模板被改坏时立即给出告警，避免扩展被悄悄拼到一个
    与文档不一致的位置。

    参数
    ----
    base
        内置 Prompt 全文。
    extensions
        按 ``内置 → 项目 → 任务`` 顺序传入的扩展片段；为空 / 仅空白字符的会跳过。
    prompt_name
        用于告警时定位是哪个模板缺 marker（planner / evaluator）。
    """
    cleaned_blocks: list[str] = []
    for ext in extensions:
        if ext is None:
            continue
        cleaned = ext.strip()
        if cleaned:
            cleaned_blocks.append(cleaned)

    if not cleaned_blocks:
        return base.rstrip()

    if PROMPT_EXTENSION_MARKER not in base:
        # marker 缺失时不阻断，但 warn 提示模板被改坏；扩展退化为末尾追加。
        logger.warning(
            "Prompt 模板缺少 '%s' marker，扩展退化为末尾追加：prompt=%s",
            PROMPT_EXTENSION_MARKER,
            prompt_name,
        )

    # marker 在文件末尾 → 追加到末尾即 marker 之后；marker 缺失也走末尾追加。
    return base.rstrip() + "\n\n" + "\n\n".join(cleaned_blocks)


def compose_planner_prompt(*extensions: str) -> str:
    """读取内置 planner prompt，按顺序在 marker 之后追加非空扩展片段。"""
    return _compose(load_planner_prompt(), extensions, prompt_name=PLANNER_PROMPT)


def compose_evaluator_prompt(*extensions: str) -> str:
    """读取内置 evaluator prompt，按顺序在 marker 之后追加非空扩展片段。"""
    return _compose(load_evaluator_prompt(), extensions, prompt_name=EVALUATOR_PROMPT)
