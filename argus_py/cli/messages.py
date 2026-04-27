"""CLI 提示文案。"""

from __future__ import annotations

LLM_CONFIG_FIELD_LABELS = {
    "LLM_API_KEY": "API Key",
    "LLM_BASE_URL": "接口地址",
    "LLM_MODEL": "模型名称",
    "LLM_MAX_TOKENS": "最大输出 Token 数",
    "LLM_TEMPERATURE": "温度",
    "LLM_MAX_RETRIES": "最大重试次数",
}

LLM_CONFIG_MESSAGES = {
    "start": "开始配置大模型 API。API Key 输入时会显示星号掩码。",
    "target": "大模型配置将写入：{path}",
    "api_key_required": "API Key 不能为空。",
    "advanced_default": "高级参数使用默认值；后续可执行 argus config llm --advanced 调整。",
    "saved": "大模型配置已写入。",
    "verify_hint": "可执行以下命令验证：",
    "keep_existing": "已配置，回车保留",
}


def llm_field_label(key: str) -> str:
    """返回 LLM 配置项的用户可见中文标签。"""
    return LLM_CONFIG_FIELD_LABELS.get(key, key)


def llm_message(key: str, **kwargs: object) -> str:
    """返回 LLM 配置流程提示文案。"""
    return LLM_CONFIG_MESSAGES[key].format(**kwargs)
