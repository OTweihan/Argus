"""任务 API Schema。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from argus_py.api.schemas.base import ApiModel, blank_to_none, strip_text
from argus_py.browser.snapshot import redact_href, redact_sensitive_text, redact_step_params
from argus_py.core.enums import FindingSeverity, FindingType, StepResult, TaskStatus, TaskType
from argus_py.task.models import Finding, Task, TaskLog


class TaskLogResponse(ApiModel):
    """任务步骤日志响应。"""

    step_number: int = Field(alias="stepNumber")
    action: str
    result: StepResult
    task_log_id: str = Field(alias="taskLogId")
    params: dict[str, Any]
    url_before: str | None = Field(default=None, alias="urlBefore")
    url_after: str | None = Field(default=None, alias="urlAfter")
    screenshot_path: str | None = Field(default=None, alias="screenshotPath")
    message: str | None = None
    error: str | None = None
    error_code: str | None = Field(default=None, alias="errorCode")
    created_at: datetime = Field(alias="createdAt")

    @classmethod
    def from_task_log(cls, log: TaskLog) -> "TaskLogResponse":
        """从任务日志实体转换响应模型。"""
        data = dict(log.__dict__)
        params = data.get("params")
        if isinstance(params, dict):
            data["params"] = redact_step_params(params)
        for url_key in ("url_before", "url_after"):
            value = data.get(url_key)
            if isinstance(value, str):
                data[url_key] = redact_href(value)
        screenshot_path = data.get("screenshot_path")
        if isinstance(screenshot_path, str):
            data["screenshot_path"] = Path(screenshot_path).name
        for text_key in ("message", "error"):
            value = data.get(text_key)
            if isinstance(value, str):
                data[text_key] = redact_sensitive_text(value)
        # error_code 是结构化失败编码，不做脱敏
        data["error_code"] = data.get("error_code")
        return cls.model_validate(data)


class FindingResponse(ApiModel):
    """问题记录响应。"""

    finding_id: str = Field(alias="findingId")
    title: str
    description: str
    severity: FindingSeverity
    finding_type: FindingType = Field(alias="findingType")
    url: str | None = None
    location: str | None = None
    screenshot_path: str | None = Field(default=None, alias="screenshotPath")
    created_at: datetime = Field(alias="createdAt")

    @classmethod
    def from_finding(cls, finding: Finding) -> "FindingResponse":
        """从问题实体转换响应模型。"""
        data = dict(finding.__dict__)
        url = data.get("url")
        if isinstance(url, str):
            data["url"] = redact_href(url)
        screenshot_path = data.get("screenshot_path")
        if isinstance(screenshot_path, str):
            data["screenshot_path"] = Path(screenshot_path).name
        for text_key in ("title", "description", "location"):
            value = data.get(text_key)
            if isinstance(value, str):
                data[text_key] = redact_sensitive_text(value)
        return cls.model_validate(data)


_PARAMS_MAX_KEYS = 100
_PARAMS_MAX_KEY_LEN = 128
_PARAMS_MAX_VALUE_STR_LEN = 10_000


class TaskCreateRequest(ApiModel):
    """创建任务请求。"""

    goal: str = Field(min_length=1, max_length=2000)
    name: str | None = Field(default=None, max_length=200)
    start_url: str | None = Field(default=None, alias="startUrl", min_length=1, max_length=2048)
    task_type: TaskType = Field(default=TaskType.BLACKBOX, alias="taskType")
    project_id: str = Field(alias="projectId", min_length=1, max_length=64)
    max_steps: int | None = Field(default=None, alias="maxSteps", gt=0, le=200)
    timeout_seconds: int | None = Field(default=None, alias="timeoutSeconds", gt=0, le=7200)
    capture_screenshots: bool | None = Field(default=None, alias="captureScreenshots")
    model_config_id: str | None = Field(default=None, alias="modelConfigId", max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=_PARAMS_MAX_KEYS)

    @field_validator("goal", "project_id", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        """必填文本去掉两端空白后再校验。"""
        return strip_text(value)

    @field_validator("name", "start_url", "model_config_id", mode="before")
    @classmethod
    def blank_optional_text_to_none(cls, value: object) -> object:
        """空白可选文本统一视为未填写。"""
        return blank_to_none(value)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        """校验参数字典的值大小。"""
        for key, val in value.items():
            if len(key) > _PARAMS_MAX_KEY_LEN:
                raise ValueError(f"参数键过长：{key[:80]}...（最多 {_PARAMS_MAX_KEY_LEN} 字符）")
            if isinstance(val, str) and len(val) > _PARAMS_MAX_VALUE_STR_LEN:
                raise ValueError(f"参数值过长：{key[:80]}（最多 {_PARAMS_MAX_VALUE_STR_LEN} 字符）")
        return value


class TaskUpdateRequest(TaskCreateRequest):
    """更新任务基础信息请求。"""


class TaskResponse(ApiModel):
    """任务响应。"""

    task_id: str = Field(alias="taskId")
    project_id: str | None = Field(default=None, alias="projectId")
    goal: str
    name: str | None = None
    start_url: str | None = Field(default=None, alias="startUrl")
    task_type: TaskType = Field(alias="taskType")
    status: TaskStatus
    scheduler_status: str | None = Field(default=None, alias="schedulerStatus")
    max_steps: int = Field(alias="maxSteps")
    timeout_seconds: int = Field(alias="timeoutSeconds")
    capture_screenshots: bool = Field(alias="captureScreenshots")
    current_step: int = Field(alias="currentStep")
    parameters: dict[str, Any]
    logs: list[TaskLogResponse]
    findings: list[FindingResponse]
    created_at: datetime = Field(alias="createdAt")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")
    report_path: str | None = Field(default=None, alias="reportPath")
    result_summary: str | None = Field(default=None, alias="resultSummary")
    error_message: str | None = Field(default=None, alias="errorMessage")

    @classmethod
    def from_task(cls, task: Task, scheduler_status: str | None = None) -> "TaskResponse":
        """从任务实体转换响应模型。"""
        return cls(
            task_id=task.task_id,
            project_id=task.project_id,
            goal=redact_sensitive_text(task.goal),
            name=task.name,
            start_url=redact_href(task.start_url) if task.start_url else None,
            task_type=task.task_type,
            status=task.status,
            scheduler_status=scheduler_status,
            max_steps=task.max_steps,
            timeout_seconds=task.timeout_seconds,
            capture_screenshots=task.capture_screenshots,
            current_step=task.current_step,
            parameters=redact_step_params(task.parameters),
            logs=[TaskLogResponse.from_task_log(log) for log in task.logs],
            findings=[FindingResponse.from_finding(finding) for finding in task.findings],
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            report_path=Path(task.report_path).name if task.report_path else None,
            result_summary=(
                redact_sensitive_text(task.result_summary) if task.result_summary else None
            ),
            error_message=(
                redact_sensitive_text(task.error_message) if task.error_message else None
            ),
        )


class TaskListResponse(ApiModel):
    """任务列表响应。"""

    total: int
    tasks: list[TaskResponse]


class TaskSummaryResponse(ApiModel):
    """轻量任务响应（不含日志和发现项），供列表页使用。"""

    task_id: str = Field(alias="taskId")
    project_id: str | None = Field(default=None, alias="projectId")
    goal: str
    name: str | None = None
    start_url: str | None = Field(default=None, alias="startUrl")
    task_type: TaskType = Field(alias="taskType")
    status: TaskStatus
    scheduler_status: str | None = Field(default=None, alias="schedulerStatus")
    max_steps: int = Field(alias="maxSteps")
    timeout_seconds: int = Field(alias="timeoutSeconds")
    capture_screenshots: bool = Field(alias="captureScreenshots")
    current_step: int = Field(alias="currentStep")
    finding_count: int = Field(alias="findingCount")
    parameters: dict[str, Any]
    created_at: datetime = Field(alias="createdAt")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")
    report_path: str | None = Field(default=None, alias="reportPath")
    result_summary: str | None = Field(default=None, alias="resultSummary")
    error_message: str | None = Field(default=None, alias="errorMessage")

    @classmethod
    def from_task(cls, task: Task, scheduler_status: str | None = None) -> "TaskSummaryResponse":
        """从任务实体转换摘要响应。"""
        return cls(
            task_id=task.task_id,
            project_id=task.project_id,
            goal=redact_sensitive_text(task.goal),
            name=task.name,
            start_url=redact_href(task.start_url) if task.start_url else None,
            task_type=task.task_type,
            status=task.status,
            scheduler_status=scheduler_status,
            max_steps=task.max_steps,
            timeout_seconds=task.timeout_seconds,
            capture_screenshots=task.capture_screenshots,
            current_step=task.current_step,
            finding_count=task.finding_count,
            parameters=redact_step_params(task.parameters),
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            report_path=Path(task.report_path).name if task.report_path else None,
            result_summary=(
                redact_sensitive_text(task.result_summary) if task.result_summary else None
            ),
            error_message=(
                redact_sensitive_text(task.error_message) if task.error_message else None
            ),
        )


class TaskSummaryListResponse(ApiModel):
    """轻量任务列表响应。"""

    total: int
    tasks: list[TaskSummaryResponse]


class TaskStartResponse(ApiModel):
    """任务启动响应。"""

    scheduler_status: str = Field(alias="schedulerStatus")
    task: TaskResponse


class InferredLimitsResponse(ApiModel):
    """推断的任务执行限制响应。"""

    max_steps: int = Field(alias="maxSteps")
    timeout_seconds: int = Field(alias="timeoutSeconds")
