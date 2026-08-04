"""JSON 读写工具。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any


def to_jsonable(value: Any) -> Any:
    """将常见 Python 对象转换为可 JSON 序列化对象。"""
    if is_dataclass(value):
        return to_jsonable(asdict(value))  # type: ignore[arg-type]
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


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> Path:
    """原子写入文本：先写同目录临时文件再 os.replace，避免撕裂/半写文件。

    幂等：并发调用时 last-write-wins，但每次落盘都是完整内容。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def write_json(path: str | Path, data: Any, indent: int = 2) -> Path:
    """以 UTF-8 原子写入 JSON。"""
    return atomic_write_text(
        path,
        json.dumps(to_jsonable(data), ensure_ascii=False, indent=indent),
    )


def read_json(path: str | Path) -> Any:
    """读取 JSON。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))
