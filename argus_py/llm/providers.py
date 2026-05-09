"""多模型供应商适配。"""

from __future__ import annotations

from dataclasses import dataclass

from argus_py.config.models import ModelConfig
from argus_py.core.constants import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_TEMPERATURE,
)
from argus_py.core.exceptions import ModelConfigError
from argus_py.llm.client import LLMClient


@dataclass(frozen=True)
class ProviderSpec:
    """供应商接入参数。"""

    provider: str
    label: str
    default_base_url: str
    completions_path: str = "/chat/completions"
    openai_compatible: bool = True
    requires_api_key: bool = True


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "dashscope": ProviderSpec(
        provider="dashscope",
        label="DashScope 百炼",
        default_base_url=DEFAULT_LLM_BASE_URL,
    ),
    "openai": ProviderSpec(
        provider="openai",
        label="OpenAI",
        default_base_url="https://api.openai.com/v1",
    ),
    "ollama": ProviderSpec(
        provider="ollama",
        label="Ollama",
        default_base_url="http://localhost:11434/v1",
        requires_api_key=False,
    ),
    "anthropic": ProviderSpec(
        provider="anthropic",
        label="Anthropic",
        default_base_url="https://api.anthropic.com/v1",
        openai_compatible=False,
    ),
    "custom": ProviderSpec(
        provider="custom",
        label="OpenAI 兼容自定义服务",
        default_base_url=DEFAULT_LLM_BASE_URL,
    ),
}


def get_provider_spec(provider: str) -> ProviderSpec:
    """获取供应商规格，未知供应商回退到 custom。"""
    return PROVIDER_SPECS.get(provider, PROVIDER_SPECS["custom"])


def default_base_url(provider: str) -> str:
    """获取供应商默认 base_url。"""
    return get_provider_spec(provider).default_base_url


def create_llm_client(config: ModelConfig) -> LLMClient:
    """基于模型配置创建 OpenAI 兼容 LLM 客户端。"""
    spec = get_provider_spec(config.provider)
    if not spec.openai_compatible:
        raise ModelConfigError(f"供应商暂未接入 OpenAI 兼容调用：{config.provider}")
    if spec.requires_api_key and not config.api_key:
        raise ModelConfigError(f"模型配置缺少 API Key：{config.model_config_id}")
    return LLMClient(
        api_key=config.api_key or "ollama",
        base_url=config.base_url or spec.default_base_url,
        model=config.model,
        max_tokens=DEFAULT_LLM_MAX_TOKENS,
        temperature=DEFAULT_LLM_TEMPERATURE,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
        completions_path=config.completions_path or spec.completions_path,
    )
