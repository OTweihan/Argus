"""共享数据解析工具——布尔值、datetime、枚举、整数。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

# ---- 布尔值解析 ----


def parse_bool(value: Any, default: bool = False) -> bool:
    """统一解析字符串/布尔值/数值为 bool。

    支持的 true 字符串（大小写不敏感）：
    ``"true"``, ``"1"``, ``"yes"``, ``"y"``, ``"on"``
    支持的 false 字符串（大小写不敏感）：
    ``"false"``, ``"0"``, ``"no"``, ``"n"``, ``"off"``
    无法识别的字符串回退到 *default*；非字符串/None 值用 ``bool(value)``。
    """
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
        return default
    return bool(value)


# ---- datetime 解析 ----


def parse_datetime(value: str | datetime | None) -> datetime | None:
    """从 JSON 或 SQLite 值还原带时区的 datetime。

    接受 ISO-8601 字符串（含 ``Z`` 后缀）或已有时区 datetime。
    缺失时区时自动赋为 UTC。
    """
    if value is None or isinstance(value, datetime):
        return value
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


# ---- 枚举解析 ----


def parse_enum(enum_class: type[Enum], value: Any) -> Any:
    """从字符串或枚举值还原枚举实例。"""
    if isinstance(value, enum_class):
        return value
    return enum_class(value)


# ---- 整数解析 ----


def parse_int_optional(value: Any) -> int | None:
    """解析可空整数，``None`` / 空字符串返回 ``None``。"""
    if value is None or value == "":
        return None
    return int(value)


def parse_int_default(value: Any, default: int) -> int:
    """解析整数，``None`` / 空字符串回退到 *default*。"""
    if value is None or value == "":
        return default
    return int(value)


def parse_float_default(value: Any, default: float) -> float:
    """解析浮点数，``None`` / 空字符串回退到 *default*。"""
    if value is None or value == "":
        return default
    return float(value)
