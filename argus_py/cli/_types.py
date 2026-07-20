"""CLI 共享类型定义，供各命令模块复用。"""

from __future__ import annotations

import argparse
from typing import Any, Protocol


class SubParserAdder(Protocol):
    """build_parser 参数协议，避免直接依赖 argparse._SubParsersAction 私有类型。"""

    def add_parser(self, name: str, **kwargs: Any) -> argparse.ArgumentParser: ...
