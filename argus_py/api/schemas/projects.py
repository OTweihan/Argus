"""项目 API Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from argus_py.api.schemas.base import ApiModel, blank_to_none, strip_text
from argus_py.project.models import Project


class ProjectCreateRequest(ApiModel):
    """创建项目请求。"""

    name: str = Field(min_length=1)
    description: str | None = None
    base_url: str | None = Field(default=None, alias="baseUrl")
    git_url: str | None = Field(default=None, alias="gitUrl")
    auth_state_name: str | None = Field(default=None, alias="authStateName")
    default_max_steps: int | None = Field(default=None, alias="defaultMaxSteps", gt=0)
    default_timeout_seconds: int | None = Field(default=None, alias="defaultTimeoutSeconds", gt=0)
    default_capture_screenshots: bool = Field(default=True, alias="defaultCaptureScreenshots")
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        """创建时去掉项目名称两端空白。"""
        return strip_text(value)

    @field_validator("description", "base_url", "git_url", "auth_state_name", mode="before")
    @classmethod
    def blank_optional_text_to_none(cls, value: object) -> object:
        """空白可选文本统一视为未填写。"""
        return blank_to_none(value)


class ProjectUpdateRequest(ApiModel):
    """更新项目请求。"""

    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    base_url: str | None = Field(default=None, alias="baseUrl")
    git_url: str | None = Field(default=None, alias="gitUrl")
    auth_state_name: str | None = Field(default=None, alias="authStateName")
    default_max_steps: int | None = Field(default=None, alias="defaultMaxSteps", gt=0)
    default_timeout_seconds: int | None = Field(default=None, alias="defaultTimeoutSeconds", gt=0)
    default_capture_screenshots: bool | None = Field(
        default=None,
        alias="defaultCaptureScreenshots",
    )
    parameters: dict[str, Any] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        """更新时去掉项目名称两端空白。"""
        return strip_text(value)

    @field_validator("description", "base_url", "git_url", "auth_state_name", mode="before")
    @classmethod
    def blank_optional_text_to_none(cls, value: object) -> object:
        """空白可选文本统一视为未填写。"""
        return blank_to_none(value)


class ProjectResponse(ApiModel):
    """项目响应。"""

    project_id: str = Field(alias="projectId")
    name: str
    description: str | None = None
    base_url: str | None = Field(default=None, alias="baseUrl")
    git_url: str | None = Field(default=None, alias="gitUrl")
    auth_state_name: str | None = Field(default=None, alias="authStateName")
    default_max_steps: int | None = Field(default=None, alias="defaultMaxSteps")
    default_timeout_seconds: int | None = Field(default=None, alias="defaultTimeoutSeconds")
    default_capture_screenshots: bool = Field(alias="defaultCaptureScreenshots")
    parameters: dict[str, Any]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @classmethod
    def from_project(cls, project: Project) -> "ProjectResponse":
        """从项目实体转换响应模型。"""
        return cls(
            project_id=project.project_id,
            name=project.name,
            description=project.description,
            base_url=project.base_url,
            git_url=project.git_url,
            auth_state_name=project.auth_state_name,
            default_max_steps=project.default_max_steps,
            default_timeout_seconds=project.default_timeout_seconds,
            default_capture_screenshots=project.default_capture_screenshots,
            parameters=project.parameters,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class ProjectListResponse(ApiModel):
    """项目列表响应。"""

    total: int = 0
    projects: list[ProjectResponse] = Field(default_factory=list)
