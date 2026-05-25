"""snake_case → camelCase 转换工具。"""

from __future__ import annotations

from typing import Any


def to_camel(snake: str) -> str:
    """将 snake_case 转换为 camelCase。"""
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def camel_keys(data: Any) -> Any:
    """递归将 dict 的所有 key 从 snake_case 转为 camelCase（返回新对象）。"""
    if isinstance(data, dict):
        return {to_camel(k): camel_keys(v) for k, v in data.items()}
    if isinstance(data, list):
        return [camel_keys(item) for item in data]
    return data


def camel_keys_inplace(data: Any) -> Any:
    """就地转换 dict key 为 camelCase，避免第二次全量拷贝。"""
    if isinstance(data, dict):
        for k in list(data.keys()):
            v = data.pop(k)
            data[to_camel(k)] = camel_keys_inplace(v)
        return data
    if isinstance(data, list):
        for i, item in enumerate(data):
            data[i] = camel_keys_inplace(item)
        return data
    return data
