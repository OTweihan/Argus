"""配置管理 API Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from argus_py.api.schemas.base import ApiModel, blank_to_none, strip_text
from argus_py.config.models import ModelConfig
from argus_py.core.enums import TaskType


class ModelConfigCreateRequest(ApiModel):
    """创建模型配置请求。"""

    name: str = Field(min_length=1)
    provider: str = ""
    model: str = Field(min_length=1)
    api_key: str = Field(default="", alias="apiKey")
    base_url: str | None = Field(default=None, alias="baseUrl")
    completions_path: str | None = Field(default=None, alias="completionsPath")
    max_retries: int | None = Field(default=None, alias="maxRetries", ge=0)
    timeout_seconds: float | None = Field(default=None, alias="timeoutSeconds", gt=0)
    task_type: TaskType | None = Field(default=None, alias="taskType")
    is_default: bool = Field(default=False, alias="isDefault")
    enabled: bool = True

    @field_validator("name", "model", "api_key", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        """创建模型配置时去掉文本两端空白。"""
        return strip_text(value)

    @field_validator("base_url", "completions_path", mode="before")
    @classmethod
    def blank_optional_text_to_none(cls, value: object) -> object:
        """空白可选文本统一视为未填写。"""
        return blank_to_none(value)


class ModelConfigUpdateRequest(ApiModel):
    """更新模型配置请求。"""

    name: str | None = Field(default=None, min_length=1)
    provider: str | None = None
    model: str | None = Field(default=None, min_length=1)
    api_key: str | None = Field(default=None, alias="apiKey")
    base_url: str | None = Field(default=None, alias="baseUrl")
    completions_path: str | None = Field(default=None, alias="completionsPath")
    max_retries: int | None = Field(default=None, alias="maxRetries", ge=0)
    timeout_seconds: float | None = Field(default=None, alias="timeoutSeconds", gt=0)
    task_type: TaskType | None = Field(default=None, alias="taskType")
    is_default: bool | None = Field(default=None, alias="isDefault")
    enabled: bool | None = None

    @field_validator("name", "model", "api_key", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        """更新模型配置时去掉文本两端空白。"""
        return strip_text(value)

    @field_validator("base_url", "completions_path", "task_type", mode="before")
    @classmethod
    def blank_optional_text_to_none(cls, value: object) -> object:
        """空白可选文本统一视为未填写。"""
        return blank_to_none(value)


class ModelConfigTestRequest(ApiModel):
    """模型连接检查请求。"""

    model_config_id: str | None = Field(default=None, alias="modelConfigId")
    provider: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, alias="apiKey")
    base_url: str | None = Field(default=None, alias="baseUrl")
    completions_path: str | None = Field(default=None, alias="completionsPath")
    max_retries: int | None = Field(default=None, alias="maxRetries", ge=0)
    timeout_seconds: float | None = Field(default=None, alias="timeoutSeconds", gt=0)

    @field_validator("model_config_id", "model", "api_key", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        """连接检查请求文本字段去掉两端空白。"""
        return strip_text(value)

    @field_validator(
        "model_config_id",
        "model",
        "api_key",
        "base_url",
        "completions_path",
        mode="before",
    )
    @classmethod
    def blank_optional_text_to_none(cls, value: object) -> object:
        """空白可选文本统一视为未填写。"""
        return blank_to_none(value)


class ModelConfigResponse(ApiModel):
    """模型配置响应，不返回 API Key 明文。"""

    model_config_id: str = Field(alias="modelConfigId")
    name: str
    provider: str
    model: str
    api_key_set: bool = Field(alias="apiKeySet")
    base_url: str = Field(alias="baseUrl")
    completions_path: str = Field(alias="completionsPath")
    max_retries: int = Field(alias="maxRetries")
    timeout_seconds: float = Field(alias="timeoutSeconds")
    task_type: TaskType | None = Field(default=None, alias="taskType")
    is_default: bool = Field(alias="isDefault")
    enabled: bool
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @classmethod
    def from_model_config(cls, config: ModelConfig) -> "ModelConfigResponse":
        """从模型配置实体转换响应模型。"""
        return cls(
            model_config_id=config.model_config_id,
            name=config.name,
            provider=config.provider,
            model=config.model,
            api_key_set=bool(config.api_key),
            base_url=config.base_url,
            completions_path=config.completions_path,
            max_retries=config.max_retries,
            timeout_seconds=config.timeout_seconds,
            task_type=config.task_type,
            is_default=config.is_default,
            enabled=config.enabled,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


class ModelConfigListResponse(ApiModel):
    """模型配置列表响应。"""

    total: int = 0
    models: list[ModelConfigResponse] = Field(default_factory=list)


class ModelConnectionTestResponse(ApiModel):
    """模型连接检查响应。"""

    success: bool
    message: str
    model: str | None = None
    latency_ms: int | None = Field(default=None, alias="latencyMs")


class ConfigSummaryResponse(ApiModel):
    """配置摘要响应，不包含敏感值。"""

    server_host: str = Field(alias="serverHost")
    server_port: int = Field(alias="serverPort")
    cors_allow_origins: list[str] = Field(alias="corsAllowOrigins")
    scheduler_concurrency: int = Field(alias="schedulerConcurrency")
    scheduler_queue_max_size: int = Field(alias="schedulerQueueMaxSize")
    scheduler_shutdown_timeout_seconds: float = Field(alias="schedulerShutdownTimeoutSeconds")
    events_history_limit: int = Field(alias="eventsHistoryLimit")
    events_subscriber_queue_size: int = Field(alias="eventsSubscriberQueueSize")
    model_configs_count: int = Field(default=0, alias="modelConfigsCount")
    default_model_config_id: str | None = Field(default=None, alias="defaultModelConfigId")
