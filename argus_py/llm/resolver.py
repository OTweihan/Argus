"""根据任务配置或全局默认解析 LLM 客户端。"""

from __future__ import annotations

from argus_py.config.llm_settings import load_llm_settings
from argus_py.config.service import ModelConfigService
from argus_py.llm.client import LLMClient
from argus_py.llm.providers import create_llm_client
from argus_py.task.models import Task


def resolve_llm_client_for_task(
    task: Task,
    model_config_service: ModelConfigService | None = None,
) -> LLMClient:
    """按任务参数或默认配置解析 LLM 客户端，未配置时回退到旧 llm.env。

    可传入共享 ``model_config_service`` 避免每任务重复构造（创建 SQLite 连接
    + 解密 api_key）；为 None 时惰性新建。
    """
    if model_config_service is None:
        from argus_py.config.service import ModelConfigService  # noqa: PLC0415

        model_config_service = ModelConfigService()
    model_config_id = _task_model_config_id(task)
    if model_config_id:
        return create_llm_client(model_config_service.get_model_config(model_config_id))

    config = model_config_service.get_default_model_config(task.task_type)
    if config is not None:
        return create_llm_client(config)

    settings = load_llm_settings()
    return LLMClient(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        max_retries=settings.max_retries,
    )


def _task_model_config_id(task: Task) -> str | None:
    """从任务参数读取模型配置 ID。"""
    value = task.parameters.get("model_config_id")
    if value is None:
        return None
    resolved = str(value).strip()
    return resolved or None
