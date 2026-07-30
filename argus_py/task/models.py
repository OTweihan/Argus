"""任务数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from argus_py.core.constants import DEFAULT_MAX_STEPS, DEFAULT_TASK_TIMEOUT_S, utc_now
from argus_py.core.enums import FindingSeverity, FindingType, StepResult, TaskStatus, TaskType
from argus_py.core.ids import generate_finding_id, generate_step_id, generate_task_id
from argus_py.utils.parse import parse_bool, parse_datetime, parse_enum

# 向后兼容别名
_parse_datetime = parse_datetime
_parse_bool = parse_bool
_parse_enum = parse_enum


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
    rule_id: str | None = None
    rule_category: str | None = None
    confidence: str | None = None
    fingerprint: str | None = None
    snippet: str | None = None
    analysis_id: str | None = None

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
            rule_id=data.get("rule_id"),
            rule_category=data.get("rule_category"),
            confidence=data.get("confidence"),
            fingerprint=data.get("fingerprint"),
            snippet=data.get("snippet"),
            analysis_id=data.get("analysis_id"),
        )


@dataclass
class Task:
    """测试任务实体。"""

    goal: str
    name: str | None = None
    start_url: str | None = None
    task_type: TaskType = TaskType.BLACKBOX
    status: TaskStatus = TaskStatus.PENDING
    task_id: str = field(default_factory=generate_task_id)
    project_id: str | None = None
    max_steps: int = DEFAULT_MAX_STEPS
    timeout_seconds: int = DEFAULT_TASK_TIMEOUT_S
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
    whitebox_config_json: str | None = None
    whitebox_config_schema_version: int = 1
    result_json: str | None = None
    result_schema_version: int | None = None
    result_size_bytes: int | None = None
    source_type: str | None = None
    source_repo_url: str | None = None
    source_requested_ref: str | None = None
    source_resolved_commit_sha: str | None = None
    source_ref_type: str | None = None
    source_dirty: bool | None = None
    external_job_id: str | None = None
    external_job_status: str | None = None
    external_job_submitted_at: str | None = None
    external_job_last_polled_at: str | None = None
    worker_id: str | None = None
    worker_lease_expires_at: str | None = None
    execution_attempt: int = 1

    def __post_init__(self) -> None:
        """初始化内部缓存字段。"""
        object.__setattr__(self, "_step_cache", None)
        object.__setattr__(self, "_finding_cache", None)

    @property
    def current_step(self) -> int:
        """当前已记录步骤数（有缓存时优先返回缓存值）。"""
        cache = self._step_cache
        if cache is not None:
            return cache
        return len(self.logs)

    @current_step.setter
    def current_step(self, value: int) -> None:
        self._step_cache = value

    @property
    def finding_count(self) -> int:
        """问题数量（有缓存时优先返回缓存值）。"""
        cache = self._finding_cache
        if cache is not None:
            return cache
        return len(self.findings)

    @finding_count.setter
    def finding_count(self, value: int) -> None:
        self._finding_cache = value

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """从 JSON 字典还原任务实体。"""
        return cls(
            goal=str(data["goal"]),
            name=data.get("name"),
            start_url=data.get("start_url"),
            task_type=_parse_enum(TaskType, data.get("task_type", TaskType.BLACKBOX.value)),
            status=_parse_enum(TaskStatus, data.get("status", TaskStatus.PENDING.value)),
            task_id=str(data.get("task_id") or generate_task_id()),
            project_id=data.get("project_id"),
            max_steps=int(data.get("max_steps", DEFAULT_MAX_STEPS)),
            timeout_seconds=int(data.get("timeout_seconds", DEFAULT_TASK_TIMEOUT_S)),
            capture_screenshots=_parse_bool(data.get("capture_screenshots"), True),
            parameters=dict(data.get("parameters") or {}),
            logs=[TaskLog.from_dict(item) for item in data.get("logs", [])],
            findings=[Finding.from_dict(item) for item in data.get("findings", [])],
            created_at=_parse_datetime(data.get("created_at")) or utc_now(),
            started_at=_parse_datetime(data.get("started_at")),
            completed_at=_parse_datetime(data.get("completed_at")),
            report_path=data.get("report_path"),
            result_summary=data.get("result_summary"),
            error_message=data.get("error_message"),
            whitebox_config_json=data.get("whitebox_config_json"),
            whitebox_config_schema_version=int(data.get("whitebox_config_schema_version", 1)),
            result_json=data.get("result_json"),
            result_schema_version=data.get("result_schema_version"),
            result_size_bytes=data.get("result_size_bytes"),
            source_type=data.get("source_type"),
            source_repo_url=data.get("source_repo_url"),
            source_requested_ref=data.get("source_requested_ref"),
            source_resolved_commit_sha=data.get("source_resolved_commit_sha"),
            source_ref_type=data.get("source_ref_type"),
            source_dirty=(
                _parse_bool(data.get("source_dirty"), default=False)
                if data.get("source_dirty") is not None
                else None
            ),
            external_job_id=data.get("external_job_id"),
            external_job_status=data.get("external_job_status"),
            external_job_submitted_at=data.get("external_job_submitted_at"),
            external_job_last_polled_at=data.get("external_job_last_polled_at"),
            worker_id=data.get("worker_id"),
            worker_lease_expires_at=data.get("worker_lease_expires_at"),
            execution_attempt=int(data.get("execution_attempt", 1)),
        )
