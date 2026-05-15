"""Prompt 业务扩展预览路由。"""

from __future__ import annotations

from fastapi import APIRouter

from argus_py.api.schemas import PromptPreviewRequest, PromptPreviewResponse
from argus_py.blackbox.prompts import (
    compose_evaluator_prompt,
    compose_planner_prompt,
    load_evaluator_prompt,
    load_planner_prompt,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.post("/preview", response_model=PromptPreviewResponse)
async def preview_prompt(request: PromptPreviewRequest) -> PromptPreviewResponse:
    """按角色返回拼接后的完整 system_prompt，用于编辑器预览。"""
    project_ext = request.project_extension or ""
    task_ext = request.task_extension or ""

    if request.role == "planner":
        builtin = load_planner_prompt()
        system_prompt = compose_planner_prompt(project_ext, task_ext)
    else:
        builtin = load_evaluator_prompt()
        system_prompt = compose_evaluator_prompt(project_ext, task_ext)

    return PromptPreviewResponse(
        system_prompt=system_prompt,
        builtin_length=len(builtin),
        project_length=len(project_ext.strip()),
        task_length=len(task_ext.strip()),
    )
