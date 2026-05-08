"""JSON 读写工具。"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any


def to_jsonable(value: Any) -> Any:
    """将常见 Python 对象转换为可 JSON 序列化对象。"""
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (BaseException, Exception)):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value


def write_json(path: str | Path, data: Any, indent: int = 2) -> Path:
    """以 UTF-8 写入 JSON。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(to_jsonable(data), ensure_ascii=False, indent=indent),
        encoding="utf-8",
    )
    return target


def read_json(path: str | Path) -> Any:
    """读取 JSON。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))
