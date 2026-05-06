"""任务 API Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from argus_py.api.schemas.base import ApiModel, blank_to_none, strip_text
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
    created_at: datetime = Field(alias="createdAt")

    @classmethod
    def from_task_log(cls, log: TaskLog) -> "TaskLogResponse":
        """从任务日志实体转换响应模型。"""
        return cls.model_validate(log.__dict__)


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
        return cls.model_validate(finding.__dict__)


class TaskCreateRequest(ApiModel):
    """创建任务请求。"""

    goal: str = Field(min_length=1)
    start_url: str | None = Field(default=None, alias="startUrl", min_length=1)
    task_type: TaskType = Field(default=TaskType.BLACKBOX, alias="taskType")
    project_id: str = Field(alias="projectId", min_length=1)
    max_steps: int | None = Field(default=None, alias="maxSteps", gt=0)
    timeout_seconds: int | None = Field(default=None, alias="timeoutSeconds", gt=0)
    capture_screenshots: bool | None = Field(default=None, alias="captureScreenshots")
    model_config_id: str | None = Field(default=None, alias="modelConfigId")
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("goal", "project_id", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        """必填文本去掉两端空白后再校验。"""
        return strip_text(value)

    @field_validator("start_url", "model_config_id", mode="before")
    @classmethod
    def blank_optional_text_to_none(cls, value: object) -> object:
        """空白可选文本统一视为未填写。"""
        return blank_to_none(value)


class TaskResponse(ApiModel):
    """任务响应。"""

    task_id: str = Field(alias="taskId")
    project_id: str | None = Field(default=None, alias="projectId")
    goal: str
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
            goal=task.goal,
            start_url=task.start_url,
            task_type=task.task_type,
            status=task.status,
            scheduler_status=scheduler_status,
            max_steps=task.max_steps,
            timeout_seconds=task.timeout_seconds,
            capture_screenshots=task.capture_screenshots,
            current_step=task.current_step,
            parameters=task.parameters,
            logs=[TaskLogResponse.from_task_log(log) for log in task.logs],
            findings=[FindingResponse.from_finding(finding) for finding in task.findings],
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            report_path=task.report_path,
            result_summary=task.result_summary,
            error_message=task.error_message,
        )


class TaskListResponse(ApiModel):
    """任务列表响应。"""

    total: int
    tasks: list[TaskResponse]


class TaskStartResponse(ApiModel):
    """任务启动响应。"""

    scheduler_status: str = Field(alias="schedulerStatus")
    task: TaskResponse
