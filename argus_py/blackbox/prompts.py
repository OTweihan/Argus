"""黑盒 Prompt 模板入口。"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from argus_py.llm.prompts import load_prompt

logger = logging.getLogger(__name__)

PLANNER_PROMPT = "blackbox_planner.md"

# 扩展片段来源标题，按 [project, task] 顺序索引。
_EXTENSION_LABELS = ["### 项目级自定义提示词", "### 任务级自定义提示词"]
EVALUATOR_PROMPT = "blackbox_evaluator.md"

# 内置 Prompt 模板里"业务扩展"区块的 marker。
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


def _compose(
    base: str,
    extensions: Iterable[str],
    *,
    prompt_name: str = "<inline>",
) -> str:
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
    for i, ext in enumerate(extensions):
        if ext is None:
            continue
        cleaned = ext.strip()
        if cleaned:
            if i < len(_EXTENSION_LABELS):
                cleaned = _EXTENSION_LABELS[i] + "\n" + cleaned
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


def compose_planner_prompt(*extensions: str, base: str | None = None) -> str:
    """读取内置 planner prompt，按顺序在 marker 之后追加非空扩展片段。

    可传入 ``base`` 跳过读取（预览路由已预加载时避免重复 I/O）。
    """
    if base is None:
        base = load_planner_prompt()
    return _compose(base, extensions, prompt_name=PLANNER_PROMPT)


def compose_evaluator_prompt(*extensions: str, base: str | None = None) -> str:
    """读取内置 evaluator prompt，按顺序在 marker 之后追加非空扩展片段。

    可传入 ``base`` 跳过读取（预览路由已预加载时避免重复 I/O）。
    """
    if base is None:
        base = load_evaluator_prompt()
    return _compose(base, extensions, prompt_name=EVALUATOR_PROMPT)
