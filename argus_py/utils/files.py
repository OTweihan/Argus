"""文件系统工具。"""

from __future__ import annotations

from pathlib import Path


def ensure_dir(path: str | Path) -> Path:
    """创建目录并返回 Path。"""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_text(path: str | Path, content: str) -> Path:
    """以 UTF-8 写入文本。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def read_text(path: str | Path) -> str:
    """以 UTF-8 读取文本。"""
    return Path(path).read_text(encoding="utf-8")
