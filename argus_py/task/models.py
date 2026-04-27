"""任务数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from argus_py.core.enums import FindingSeverity, FindingType, StepResult, TaskStatus, TaskType
from argus_py.core.ids import generate_finding_id, generate_step_id, generate_task_id


def utc_now() -> datetime:
    """返回 UTC 当前时间。"""
    return datetime.now(timezone.utc)


@dataclass
class TaskLog:
    """任务执行步骤日志。"""

    step_number: int
    action: str
    result: StepResult = StepResult.SUCCESS
    task_log_id: str = field(default_factory=generate_step_id)
    params: dict[str, Any] = field(default_factory=dict)
    url_before: str | None = None
    url_after: str | None = None
    screenshot_path: str | None = None
    message: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Finding:
    """测试过程中发现的问题或观察项。"""

    title: str
    description: str
    severity: FindingSeverity = FindingSeverity.INFO
    finding_type: FindingType = FindingType.FUNCTIONAL
    finding_id: str = field(default_factory=generate_finding_id)
    url: str | None = None
    location: str | None = None
    screenshot_path: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Task:
    """测试任务实体。"""

    goal: str
    start_url: str | None = None
    task_type: TaskType = TaskType.BLACKBOX
    status: TaskStatus = TaskStatus.PENDING
    task_id: str = field(default_factory=generate_task_id)
    project_id: str | None = None
    max_steps: int = 20
    timeout_seconds: int = 300
    capture_screenshots: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)
    logs: list[TaskLog] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    report_path: str | None = None
    result_summary: str | None = None
    error_message: str | None = None

    @property
    def current_step(self) -> int:
        """当前已记录步骤数。"""
        return len(self.logs)
