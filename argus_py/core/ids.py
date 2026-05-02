"""ID 生成工具。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def generate_id(prefix: str = "arg") -> str:
    """生成短 ID，格式为 prefix-时间戳-随机串。"""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = uuid4().hex[:8]
    return f"{prefix}-{timestamp}-{suffix}"


def generate_task_id() -> str:
    """生成任务 ID。"""
    return generate_id("task")


def generate_project_id() -> str:
    """生成项目 ID。"""
    return generate_id("proj")


def generate_model_config_id() -> str:
    """生成模型配置 ID。"""
    return generate_id("model")


def generate_step_id() -> str:
    """生成步骤 ID。"""
    return generate_id("step")


def generate_finding_id() -> str:
    """生成问题 ID。"""
    return generate_id("find")


def generate_report_id() -> str:
    """生成报告 ID。"""
    return generate_id("report")
