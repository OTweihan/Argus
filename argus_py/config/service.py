"""模型配置管理服务。"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from argus_py.config.model_storage import ModelConfigSQLiteStorage
from argus_py.config.models import ModelConfig
from argus_py.core.constants import (
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_TEMPERATURE,
)
from argus_py.core.enums import TaskType
from argus_py.core.exceptions import ModelConfigError
from argus_py.llm.models import ChatMessage
from argus_py.llm.providers import create_llm_client, default_base_url, get_provider_spec


class ModelConfigService:
    """模型配置 CRUD 和连接检查服务。"""

    def __init__(self, storage: ModelConfigSQLiteStorage | None = None) -> None:
        self.storage = storage or ModelConfigSQLiteStorage()

    def create_model_config(
        self,
        name: str,
        provider: str = "",
        model: str = "",
        api_key: str = "",
        base_url: str | None = None,
        completions_path: str | None = None,
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
        task_type: TaskType | None = None,
        is_default: bool = False,
        enabled: bool = True,
    ) -> ModelConfig:
        """创建模型配置。"""
        resolved_name = name.strip()
        if not resolved_name:
            raise ModelConfigError("模型配置名称不能为空。")
        resolved_model = model.strip()
        if not resolved_model:
            raise ModelConfigError("模型名称不能为空。")

        spec = get_provider_spec(provider)
        config = ModelConfig(
            name=resolved_name,
            provider=provider,
            model=resolved_model,
            api_key=api_key.strip(),
            base_url=_normalize_base_url(base_url) or spec.default_base_url,
            completions_path=_normalize_completions_path(completions_path or spec.completions_path),
            max_retries=max_retries if max_retries is not None else DEFAULT_LLM_MAX_RETRIES,
            timeout_seconds=timeout_seconds if timeout_seconds is not None else 120.0,
            task_type=task_type,
            is_default=is_default,
            enabled=enabled,
        )
        return self.storage.save(config)

    def get_model_config(self, model_config_id: str) -> ModelConfig:
        """查询模型配置。"""
        return self.storage.load(model_config_id)

    def list_model_configs(self, include_disabled: bool = True) -> list[ModelConfig]:
        """列出模型配置。"""
        return self.storage.list_configs(include_disabled=include_disabled)

    def update_model_config(self, model_config_id: str, updates: dict[str, Any]) -> ModelConfig:
        """局部更新模型配置。"""
        config = self.get_model_config(model_config_id)
        previous_provider = config.provider
        provider_changed = "provider" in updates
        base_url_overridden = "base_url" in updates
        completions_path_overridden = "completions_path" in updates
        for field_name, value in updates.items():
            if field_name == "name":
                value = str(value).strip()
                if not value:
                    raise ModelConfigError("模型配置名称不能为空。")
            if field_name == "model":
                value = str(value).strip()
                if not value:
                    raise ModelConfigError("模型名称不能为空。")
            if field_name == "provider":
                value = str(value)
            if field_name == "api_key":
                value = "" if value is None else str(value).strip()
            if field_name == "base_url":
                value = _normalize_base_url(value)
            if field_name == "completions_path":
                value = _normalize_completions_path(value)
            if field_name == "task_type" and value is not None:
                value = TaskType(str(value))
            if field_name == "task_type" and value == "":
                value = None
            if not hasattr(config, field_name):
                raise ModelConfigError(f"不支持更新的模型配置字段：{field_name}")
            setattr(config, field_name, value)

        if not config.base_url:
            config.base_url = default_base_url(config.provider)
        if provider_changed:
            spec = get_provider_spec(config.provider)
            previous_spec = get_provider_spec(previous_provider)
            if not base_url_overridden or config.base_url == previous_spec.default_base_url:
                config.base_url = spec.default_base_url
            if (
                not completions_path_overridden
                or config.completions_path == previous_spec.completions_path
            ):
                config.completions_path = spec.completions_path
        config.updated_at = datetime.now(timezone.utc)
        return self.storage.save(config)

    def delete_model_config(self, model_config_id: str) -> None:
        """删除模型配置。"""
        self.storage.delete(model_config_id)

    async def test_model_config(self, config: ModelConfig) -> dict[str, Any]:
        """检查模型配置是否可以完成一次低成本调用。

        使用 ``async with`` 确保底层 httpx 连接池被显式关闭，避免一次性
        连通性检查后留下未关闭的 AsyncClient 触发资源警告。
        """
        started = time.perf_counter()
        async with create_llm_client(config) as client:
            response = await client.chat(
                [
                    ChatMessage(
                        role="user",
                        content="请只回复 OK，用于连通性检查。",
                    )
                ]
            )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "success": True,
            "message": "模型连接检查通过。",
            "model": response.model or config.model,
            "latencyMs": elapsed_ms,
        }

    def get_default_model_config(self, task_type: TaskType | None = None) -> ModelConfig | None:
        """获取默认模型配置。"""
        return self.storage.find_default(task_type=task_type)


def _normalize_base_url(value: str | None) -> str | None:
    """规范化 base_url。"""
    if value is None:
        return None
    stripped = str(value).strip().rstrip("/")
    return stripped or None


def _normalize_completions_path(value: str | None) -> str:
    """规范化 Chat Completions 路径。"""
    stripped = str(value or "/chat/completions").strip()
    if not stripped:
        stripped = "/chat/completions"
    return stripped if stripped.startswith("/") else f"/{stripped}"
