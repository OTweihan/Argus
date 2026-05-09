"""模型配置数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from argus_py.core.constants import (
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
)
from argus_py.core.enums import TaskType
from argus_py.core.ids import generate_model_config_id
from argus_py.project.models import parse_datetime


ModelProvider = str


def utc_now() -> datetime:
    """返回 UTC 当前时间。"""
    return datetime.now(timezone.utc)


@dataclass
class ModelConfig:
    """模型配置实体。"""

    name: str
    provider: str = ""
    model: str = DEFAULT_LLM_MODEL
    base_url: str = ""
    model_config_id: str = field(default_factory=generate_model_config_id)
    api_key: str = ""
    completions_path: str = "/chat/completions"
    max_retries: int = DEFAULT_LLM_MAX_RETRIES
    timeout_seconds: float = 120.0
    task_type: TaskType | None = None
    is_default: bool = False
    enabled: bool = True
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelConfig":
        """从字典还原模型配置实体。"""
        return cls(
            name=str(data["name"]),
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or DEFAULT_LLM_MODEL),
            base_url=str(data.get("base_url") or ""),
            model_config_id=str(data.get("model_config_id") or generate_model_config_id()),
            api_key=str(data.get("api_key") or ""),
            completions_path=str(data.get("completions_path") or "/chat/completions"),
            max_retries=_int_or_default(data.get("max_retries"), DEFAULT_LLM_MAX_RETRIES),
            timeout_seconds=_float_or_default(data.get("timeout_seconds"), 120.0),
            task_type=_parse_task_type(data.get("task_type")),
            is_default=bool(data.get("is_default", False)),
            enabled=bool(data.get("enabled", True)),
            created_at=parse_datetime(data.get("created_at")) or utc_now(),
            updated_at=parse_datetime(data.get("updated_at")) or utc_now(),
        )


def _parse_task_type(value: Any) -> TaskType | None:
    """解析可空任务类型。"""
    if value is None or value == "":
        return None
    return TaskType(str(value))


def _int_or_default(value: Any, default: int) -> int:
    """解析整数，允许 0。"""
    if value is None or value == "":
        return default
    return int(value)


def _float_or_default(value: Any, default: float) -> float:
    """解析浮点数，允许 0。"""
    if value is None or value == "":
        return default
    return float(value)
