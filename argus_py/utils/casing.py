"""snake_case ↔ camelCase 转换工具。"""

from __future__ import annotations

from typing import Any


def to_camel(snake: str) -> str:
    """将 snake_case 转换为 camelCase。"""
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def camel_keys(data: Any) -> Any:
    """递归将 dict 的所有 key 从 snake_case 转为 camelCase。"""
    if isinstance(data, dict):
        return {to_camel(k): camel_keys(v) for k, v in data.items()}
    if isinstance(data, list):
        return [camel_keys(item) for item in data]
    return data
