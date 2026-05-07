"""LLM 配置加载。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from argus_py.core.crypto import decrypt_api_key
from argus_py.core.paths import LLM_ENV_FILE
from argus_py.core.constants import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
)

DEFAULT_LLM_ENV_FILE = LLM_ENV_FILE


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


@dataclass(frozen=True)
class LLMSettings:
    """LLM API 配置。"""

    api_key: str
    base_url: str = DEFAULT_LLM_BASE_URL
    model: str = DEFAULT_LLM_MODEL
    max_tokens: int = DEFAULT_LLM_MAX_TOKENS
    temperature: float = DEFAULT_LLM_TEMPERATURE
    max_retries: int = DEFAULT_LLM_MAX_RETRIES


def load_llm_settings(env_file: str | Path = DEFAULT_LLM_ENV_FILE) -> LLMSettings:
    """从独立 LLM env 文件和环境变量加载配置。"""
    env_path = Path(env_file)
    if env_path.exists():
        load_dotenv(env_path, override=False)

    return LLMSettings(
        api_key=decrypt_api_key(os.getenv("LLM_API_KEY", "")),
        base_url=os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        model=os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
        max_tokens=_env_int("LLM_MAX_TOKENS", DEFAULT_LLM_MAX_TOKENS),
        temperature=_env_float("LLM_TEMPERATURE", DEFAULT_LLM_TEMPERATURE),
        max_retries=_env_int("LLM_MAX_RETRIES", DEFAULT_LLM_MAX_RETRIES),
    )
