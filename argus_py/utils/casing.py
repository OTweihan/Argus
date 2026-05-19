"""snake_case ↔ camelCase 转换工具。"""

from __future__ import annotations

import re
from typing import Any

# 正则：在"小写/数字→大写"和"连续大写→大写+小写"边界补下划线
# 预编译避免每次调用 re.compile
_SNAKE_RE1 = re.compile(r"([a-z0-9])([A-Z])")  # camelCase → camel_Case
_SNAKE_RE2 = re.compile(r"([A-Z]+)([A-Z][a-z])")  # URLConfig → URL_Config


def to_camel(snake: str) -> str:
    """将 snake_case 转换为 camelCase。"""
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def to_snake(camel: str) -> str:
    """将 camelCase / PascalCase 转换为 snake_case。

    能正确处理连续大写缩写（URL → url、taskID → task_id）和前导下划线。

    >>> to_snake("taskID")
    'task_id'
    >>> to_snake("URLConfig")
    'url_config'
    >>> to_snake("_private")
    '_private'
    >>> to_snake("parseURL")
    'parse_url'
    """
    s = _SNAKE_RE1.sub(r"\1_\2", camel)
    s = _SNAKE_RE2.sub(r"\1_\2", s)
    return s.lower()


def camel_keys(data: Any) -> Any:
    """递归将 dict 的所有 key 从 snake_case 转为 camelCase。"""
    if isinstance(data, dict):
        return {to_camel(k): camel_keys(v) for k, v in data.items()}
    if isinstance(data, list):
        return [camel_keys(item) for item in data]
    return data


def snake_keys(data: Any) -> Any:
    """递归将 dict 的所有 key 从 camelCase 转为 snake_case。

    ``camel_keys(snake_keys(d))`` 与原始数据一致（单射），
    反向亦然（全量覆盖 camelCase -> snake_case 即可还原）。
    """
    if isinstance(data, dict):
        return {to_snake(k): snake_keys(v) for k, v in data.items()}
    if isinstance(data, list):
        return [snake_keys(item) for item in data]
    return data
