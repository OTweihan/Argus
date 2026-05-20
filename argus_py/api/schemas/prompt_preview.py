"""Prompt 业务扩展预览 API Schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from argus_py.api.schemas.base import ApiModel

PromptRole = Literal["planner", "evaluator"]

# 单字段长度上限。Prompt 扩展是人工填写的辅助文本，64KB 远超正常使用，
# 同时给 DoS / 误粘超大 JSON 一个明确边界。超限时 Pydantic 会抛
# RequestValidationError，由 middleware 转 422 响应。
_MAX_EXTENSION_LENGTH = 64 * 1024


class PromptPreviewRequest(ApiModel):
    """Prompt 扩展拼接预览请求。"""

    role: PromptRole = Field(description="预览的 Prompt 角色：planner 或 evaluator")
    project_extension: str = Field(
        default="",
        alias="projectExtension",
        max_length=_MAX_EXTENSION_LENGTH,
        description="项目级扩展，最长 64KB",
    )
    task_extension: str = Field(
        default="",
        alias="taskExtension",
        max_length=_MAX_EXTENSION_LENGTH,
        description="任务级扩展，最长 64KB",
    )


class PromptPreviewResponse(ApiModel):
    """Prompt 扩展拼接预览响应。"""

    system_prompt: str = Field(alias="systemPrompt")
    builtin_length: int = Field(alias="builtinLength")
    project_length: int = Field(alias="projectLength")
    task_length: int = Field(alias="taskLength")
