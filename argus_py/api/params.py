"""API 路由公共参数 —— 消灭重复的 Path(pattern) 样板。"""

from typing import Annotated

from fastapi import Path

TaskIdPath = Annotated[str, Path(pattern=r"^task-[a-zA-Z0-9-]+$")]
"""所有 task_id 路径参数的统一校验模式。"""
