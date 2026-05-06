"""API Schema 基类。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """API 模型基类，允许同时使用 snake_case 和 camelCase 输入。"""

    model_config = ConfigDict(populate_by_name=True)


def strip_text(value: object) -> object:
    """字符串去掉两端空白，其他类型交给 Pydantic 继续校验。"""
    return value.strip() if isinstance(value, str) else value


def blank_to_none(value: object) -> object:
    """空白字符串转换为 None。"""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    return stripped or None
