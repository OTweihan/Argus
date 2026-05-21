"""Planer/Evaluator 共享的 LLMClient 懒加载工厂。"""

from __future__ import annotations

from argus_py.config.llm_settings import load_llm_settings
from argus_py.llm.client import LLMClient


def create_llm_client() -> LLMClient:
    """创建 LLM 客户端（使用全局 settings）。"""
    settings = load_llm_settings()
    return LLMClient(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        max_tokens=settings.max_tokens,
        temperature=settings.temperature,
        max_retries=settings.max_retries,
    )
