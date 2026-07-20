"""项目数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from argus_py.core.constants import utc_now
from argus_py.core.ids import generate_project_id
from argus_py.utils.parse import parse_datetime, parse_int_optional

# 向后兼容：parse_datetime 仍从这里导入
# (config/models.py, task/repositories/mappers.py 等通过 project.models 引用)
__all__ = ["Project", "parse_datetime", "parse_int_optional"]


@dataclass
class Project:
    """项目配置实体。"""

    name: str
    project_id: str = field(default_factory=generate_project_id)
    description: str | None = None
    base_url: str | None = None
    git_url: str | None = None
    auth_state_name: str | None = None
    default_max_steps: int | None = None
    default_timeout_seconds: int | None = None
    default_capture_screenshots: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        """从字典还原项目实体。"""
        return cls(
            name=str(data["name"]),
            project_id=str(data.get("project_id") or generate_project_id()),
            description=data.get("description"),
            base_url=data.get("base_url"),
            git_url=data.get("git_url"),
            auth_state_name=data.get("auth_state_name"),
            default_max_steps=parse_int_optional(data.get("default_max_steps")),
            default_timeout_seconds=parse_int_optional(data.get("default_timeout_seconds")),
            default_capture_screenshots=bool(data.get("default_capture_screenshots", True)),
            parameters=dict(data.get("parameters") or {}),
            created_at=parse_datetime(data.get("created_at")) or utc_now(),
            updated_at=parse_datetime(data.get("updated_at")) or utc_now(),
        )
