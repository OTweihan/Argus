"""Planner/Evaluator 共享的 LLMClient 懒加载工厂 — 从 SQLite 读取默认配置。"""

from __future__ import annotations

from argus_py.config.service import ModelConfigService
from argus_py.llm.client import LLMClient
from argus_py.llm.providers import create_llm_client as _create_from_config


def create_default_client() -> LLMClient:
    """创建 LLM 客户端（使用 SQLite 中默认模型配置）。"""
    service = ModelConfigService()
    config = service.get_default_model_config()
    if config is not None:
        return _create_from_config(config)

    from argus_py.core.exceptions import ModelConfigError

    raise ModelConfigError("未配置模型。请先执行: argus config llm")
