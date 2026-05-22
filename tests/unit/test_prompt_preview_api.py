"""验证 POST /prompts/preview 的拼接逻辑与角色路由。"""

from __future__ import annotations

import pytest
from argus_py.api.routes import prompts as prompt_routes
from argus_py.api.schemas import PromptPreviewRequest


@pytest.mark.asyncio
async def test_preview_planner_without_extensions_equals_builtin():
    response = await prompt_routes.preview_prompt(PromptPreviewRequest(role="planner"))

    assert response.builtin_length > 0
    assert response.project_length == 0
    assert response.task_length == 0
    assert response.system_prompt.startswith("你是 Argus 黑盒测试规划器")


@pytest.mark.asyncio
async def test_preview_evaluator_without_extensions_equals_builtin():
    response = await prompt_routes.preview_prompt(PromptPreviewRequest(role="evaluator"))

    assert response.builtin_length > 0
    assert response.system_prompt.startswith("你是 Argus 黑盒测试结果评估器")


@pytest.mark.asyncio
async def test_preview_planner_concatenates_project_then_task():
    response = await prompt_routes.preview_prompt(
        PromptPreviewRequest(
            role="planner",
            projectExtension="PROJ_PLAN_MARKER",
            taskExtension="TASK_PLAN_MARKER",
        )
    )

    assert "PROJ_PLAN_MARKER" in response.system_prompt
    assert "TASK_PLAN_MARKER" in response.system_prompt
    assert response.system_prompt.index("PROJ_PLAN_MARKER") < response.system_prompt.index(
        "TASK_PLAN_MARKER"
    )
    assert response.project_length == len("PROJ_PLAN_MARKER")
    assert response.task_length == len("TASK_PLAN_MARKER")


@pytest.mark.asyncio
async def test_preview_evaluator_appends_extensions_at_tail():
    response = await prompt_routes.preview_prompt(
        PromptPreviewRequest(
            role="evaluator",
            projectExtension="EVAL_PROJ_MARKER",
            taskExtension="EVAL_TASK_MARKER",
        )
    )

    assert response.system_prompt.rstrip().endswith("EVAL_TASK_MARKER")
    assert response.system_prompt.index("EVAL_PROJ_MARKER") < response.system_prompt.index(
        "EVAL_TASK_MARKER"
    )


@pytest.mark.asyncio
async def test_preview_skips_whitespace_only_extensions():
    response = await prompt_routes.preview_prompt(
        PromptPreviewRequest(
            role="planner",
            projectExtension="   ",
            taskExtension="\n\t  \n",
        )
    )

    assert response.project_length == 0
    assert response.task_length == 0
    # 内置 prompt 末尾应保留 "## 业务扩展" marker，但不再被任何用户片段污染
    assert response.system_prompt.rstrip().endswith(
        "以下规则由调用方按项目和任务追加；若与上述安全边界冲突，仍以上述安全边界为准。"
    )


def test_invalid_role_rejected_by_schema():
    with pytest.raises(ValueError):
        PromptPreviewRequest(role="unknown")
