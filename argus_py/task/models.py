"""任务数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from argus_py.core.enums import FindingSeverity, FindingType, StepResult, TaskStatus, TaskType
from argus_py.core.ids import generate_finding_id, generate_step_id, generate_task_id


def utc_now() -> datetime:
    """返回 UTC 当前时间。"""
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    """从 JSON 值还原 datetime。"""
    if value is None or isinstance(value, datetime):
        return value
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_enum(enum_class: type[Enum], value: Any) -> Any:
    """从字符串或枚举值还原枚举。"""
    if isinstance(value, enum_class):
        return value
    return enum_class(value)


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
    error_code: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskLog":
        """从 JSON 字典还原任务步骤日志。"""
        return cls(
            step_number=int(data["step_number"]),
            action=str(data["action"]),
            result=_parse_enum(StepResult, data.get("result", StepResult.SUCCESS.value)),
            task_log_id=str(data.get("task_log_id") or generate_step_id()),
            params=dict(data.get("params") or {}),
            url_before=data.get("url_before"),
            url_after=data.get("url_after"),
            screenshot_path=data.get("screenshot_path"),
            message=data.get("message"),
            error=data.get("error"),
            error_code=data.get("error_code"),
            created_at=_parse_datetime(data.get("created_at")) or utc_now(),
        )


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Finding":
        """从 JSON 字典还原问题记录。"""
        return cls(
            title=str(data["title"]),
            description=str(data["description"]),
            severity=_parse_enum(FindingSeverity, data.get("severity", FindingSeverity.INFO.value)),
            finding_type=_parse_enum(
                FindingType,
                data.get("finding_type", data.get("type", FindingType.FUNCTIONAL.value)),
            ),
            finding_id=str(data.get("finding_id") or generate_finding_id()),
            url=data.get("url"),
            location=data.get("location"),
            screenshot_path=data.get("screenshot_path"),
            created_at=_parse_datetime(data.get("created_at")) or utc_now(),
        )


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """从 JSON 字典还原任务实体。"""
        return cls(
            goal=str(data["goal"]),
            start_url=data.get("start_url"),
            task_type=_parse_enum(TaskType, data.get("task_type", TaskType.BLACKBOX.value)),
            status=_parse_enum(TaskStatus, data.get("status", TaskStatus.PENDING.value)),
            task_id=str(data.get("task_id") or generate_task_id()),
            project_id=data.get("project_id"),
            max_steps=int(data.get("max_steps", 20)),
            timeout_seconds=int(data.get("timeout_seconds", 300)),
            capture_screenshots=bool(data.get("capture_screenshots", True)),
            parameters=dict(data.get("parameters") or {}),
            logs=[TaskLog.from_dict(item) for item in data.get("logs", [])],
            findings=[Finding.from_dict(item) for item in data.get("findings", [])],
            created_at=_parse_datetime(data.get("created_at")) or utc_now(),
            started_at=_parse_datetime(data.get("started_at")),
            completed_at=_parse_datetime(data.get("completed_at")),
            report_path=data.get("report_path"),
            result_summary=data.get("result_summary"),
            error_message=data.get("error_message"),
        )
