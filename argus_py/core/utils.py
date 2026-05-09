"""共享工具函数。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    """返回 UTC 当前时间。"""
    return datetime.now(timezone.utc)


def parse_datetime(value: str | datetime | None) -> datetime | None:
    """从 JSON 或 SQLite 值还原 datetime。"""
    if value is None or isinstance(value, datetime):
        return value
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def coerce_bool(value: Any, default: bool) -> bool:
    """将常见布尔写法统一转换为 bool。"""
    if value is None:
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


def coerce_int(value: Any, default: int, minimum: int | None = None) -> int:
    """将值转换为 int，非法值回退默认值。"""
    try:
        resolved = int(value if value is not None else default)
    except (TypeError, ValueError):
        resolved = default
    return max(minimum, resolved) if minimum is not None else resolved


def coerce_float(value: Any, default: float, minimum: float | None = None) -> float:
    """将值转换为 float，非法值回退默认值。"""
    try:
        resolved = float(value if value is not None else default)
    except (TypeError, ValueError):
        resolved = default
    return max(minimum, resolved) if minimum is not None else resolved


# ---- env 变量读取辅助 --------------------------------------------------------


def env_bool(name: str, default: bool) -> bool:
    """从环境变量读取布尔值。"""
    return coerce_bool(os.getenv(name), default)


def env_int(name: str, default: int) -> int:
    """从环境变量读取整数。"""
    return coerce_int(os.getenv(name), default)


def env_float(name: str, default: float) -> float:
    """从环境变量读取浮点数。"""
    return coerce_float(os.getenv(name), default)
