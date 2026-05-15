"""Prompt 业务扩展预览 API Schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from argus_py.api.schemas.base import ApiModel

PromptRole = Literal["planner", "evaluator"]


class PromptPreviewRequest(ApiModel):
    """Prompt 扩展拼接预览请求。"""

    role: PromptRole = Field(description="预览的 Prompt 角色：planner 或 evaluator")
    project_extension: str = Field(default="", alias="projectExtension")
    task_extension: str = Field(default="", alias="taskExtension")


class PromptPreviewResponse(ApiModel):
    """Prompt 扩展拼接预览响应。"""

    system_prompt: str = Field(alias="systemPrompt")
    builtin_length: int = Field(alias="builtinLength")
    project_length: int = Field(alias="projectLength")
    task_length: int = Field(alias="taskLength")
