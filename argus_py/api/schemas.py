"""API 请求与响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from argus_py.config.models import ModelConfig, ModelProvider
from argus_py.core.enums import FindingSeverity, FindingType, StepResult, TaskStatus, TaskType
from argus_py.project.models import Project
from argus_py.task.models import Finding, Task, TaskLog


class ApiModel(BaseModel):
    """API 模型基类，允许同时使用 snake_case 和 camelCase 输入。"""

    model_config = ConfigDict(populate_by_name=True)


class HealthResponse(ApiModel):
    """健康检查响应。"""

    status: str
    version: str
    project: str


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


class TaskResponse(ApiModel):
    """任务响应。"""

    task_id: str = Field(alias="taskId")
    project_id: str | None = Field(default=None, alias="projectId")
    goal: str
    start_url: str | None = Field(default=None, alias="startUrl")
    task_type: TaskType = Field(alias="taskType")
    status: TaskStatus
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
    def from_task(cls, task: Task) -> "TaskResponse":
        """从任务实体转换响应模型。"""
        return cls(
            task_id=task.task_id,
            project_id=task.project_id,
            goal=task.goal,
            start_url=task.start_url,
            task_type=task.task_type,
            status=task.status,
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


class ProjectCreateRequest(ApiModel):
    """创建项目请求。"""

    name: str = Field(min_length=1)
    description: str | None = None
    base_url: str | None = Field(default=None, alias="baseUrl")
    git_url: str | None = Field(default=None, alias="gitUrl")
    auth_state_name: str | None = Field(default=None, alias="authStateName")
    default_max_steps: int | None = Field(default=None, alias="defaultMaxSteps", gt=0)
    default_timeout_seconds: int | None = Field(default=None, alias="defaultTimeoutSeconds", gt=0)
    default_capture_screenshots: bool = Field(default=True, alias="defaultCaptureScreenshots")
    parameters: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdateRequest(ApiModel):
    """更新项目请求。"""

    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    base_url: str | None = Field(default=None, alias="baseUrl")
    git_url: str | None = Field(default=None, alias="gitUrl")
    auth_state_name: str | None = Field(default=None, alias="authStateName")
    default_max_steps: int | None = Field(default=None, alias="defaultMaxSteps", gt=0)
    default_timeout_seconds: int | None = Field(default=None, alias="defaultTimeoutSeconds", gt=0)
    default_capture_screenshots: bool | None = Field(
        default=None,
        alias="defaultCaptureScreenshots",
    )
    parameters: dict[str, Any] | None = None


class ProjectResponse(ApiModel):
    """项目响应。"""

    project_id: str = Field(alias="projectId")
    name: str
    description: str | None = None
    base_url: str | None = Field(default=None, alias="baseUrl")
    git_url: str | None = Field(default=None, alias="gitUrl")
    auth_state_name: str | None = Field(default=None, alias="authStateName")
    default_max_steps: int | None = Field(default=None, alias="defaultMaxSteps")
    default_timeout_seconds: int | None = Field(default=None, alias="defaultTimeoutSeconds")
    default_capture_screenshots: bool = Field(alias="defaultCaptureScreenshots")
    parameters: dict[str, Any]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @classmethod
    def from_project(cls, project: Project) -> "ProjectResponse":
        """从项目实体转换响应模型。"""
        return cls(
            project_id=project.project_id,
            name=project.name,
            description=project.description,
            base_url=project.base_url,
            git_url=project.git_url,
            auth_state_name=project.auth_state_name,
            default_max_steps=project.default_max_steps,
            default_timeout_seconds=project.default_timeout_seconds,
            default_capture_screenshots=project.default_capture_screenshots,
            parameters=project.parameters,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class ProjectListResponse(ApiModel):
    """项目列表响应。"""

    total: int = 0
    projects: list[ProjectResponse] = Field(default_factory=list)


class ModelConfigCreateRequest(ApiModel):
    """创建模型配置请求。"""

    name: str = Field(min_length=1)
    provider: ModelProvider = ModelProvider.DASHSCOPE
    model: str = Field(min_length=1)
    api_key: str = Field(default="", alias="apiKey")
    base_url: str | None = Field(default=None, alias="baseUrl")
    completions_path: str | None = Field(default=None, alias="completionsPath")
    max_tokens: int | None = Field(default=None, alias="maxTokens", gt=0)
    temperature: float | None = Field(default=None, ge=0)
    max_retries: int | None = Field(default=None, alias="maxRetries", ge=0)
    timeout_seconds: float | None = Field(default=None, alias="timeoutSeconds", gt=0)
    task_type: TaskType | None = Field(default=None, alias="taskType")
    is_default: bool = Field(default=False, alias="isDefault")
    enabled: bool = True


class ModelConfigUpdateRequest(ApiModel):
    """更新模型配置请求。"""

    name: str | None = Field(default=None, min_length=1)
    provider: ModelProvider | None = None
    model: str | None = Field(default=None, min_length=1)
    api_key: str | None = Field(default=None, alias="apiKey")
    base_url: str | None = Field(default=None, alias="baseUrl")
    completions_path: str | None = Field(default=None, alias="completionsPath")
    max_tokens: int | None = Field(default=None, alias="maxTokens", gt=0)
    temperature: float | None = Field(default=None, ge=0)
    max_retries: int | None = Field(default=None, alias="maxRetries", ge=0)
    timeout_seconds: float | None = Field(default=None, alias="timeoutSeconds", gt=0)
    task_type: TaskType | None = Field(default=None, alias="taskType")
    is_default: bool | None = Field(default=None, alias="isDefault")
    enabled: bool | None = None


class ModelConfigTestRequest(ApiModel):
    """模型连接检查请求。"""

    model_config_id: str | None = Field(default=None, alias="modelConfigId")
    provider: ModelProvider | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, alias="apiKey")
    base_url: str | None = Field(default=None, alias="baseUrl")
    completions_path: str | None = Field(default=None, alias="completionsPath")
    max_tokens: int | None = Field(default=None, alias="maxTokens", gt=0)
    temperature: float | None = Field(default=None, ge=0)
    max_retries: int | None = Field(default=None, alias="maxRetries", ge=0)
    timeout_seconds: float | None = Field(default=None, alias="timeoutSeconds", gt=0)


class ModelConfigResponse(ApiModel):
    """模型配置响应，不返回 API Key 明文。"""

    model_config_id: str = Field(alias="modelConfigId")
    name: str
    provider: ModelProvider
    model: str
    api_key_set: bool = Field(alias="apiKeySet")
    base_url: str = Field(alias="baseUrl")
    completions_path: str = Field(alias="completionsPath")
    max_tokens: int = Field(alias="maxTokens")
    temperature: float
    max_retries: int = Field(alias="maxRetries")
    timeout_seconds: float = Field(alias="timeoutSeconds")
    task_type: TaskType | None = Field(default=None, alias="taskType")
    is_default: bool = Field(alias="isDefault")
    enabled: bool
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @classmethod
    def from_model_config(cls, config: ModelConfig) -> "ModelConfigResponse":
        """从模型配置实体转换响应模型。"""
        return cls(
            model_config_id=config.model_config_id,
            name=config.name,
            provider=config.provider,
            model=config.model,
            api_key_set=bool(config.api_key),
            base_url=config.base_url,
            completions_path=config.completions_path,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            max_retries=config.max_retries,
            timeout_seconds=config.timeout_seconds,
            task_type=config.task_type,
            is_default=config.is_default,
            enabled=config.enabled,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


class ModelConfigListResponse(ApiModel):
    """模型配置列表响应。"""

    total: int = 0
    models: list[ModelConfigResponse] = Field(default_factory=list)


class ModelConnectionTestResponse(ApiModel):
    """模型连接检查响应。"""

    success: bool
    message: str
    model: str | None = None
    latency_ms: int | None = Field(default=None, alias="latencyMs")


class ConfigSummaryResponse(ApiModel):
    """配置摘要响应，不包含敏感值。"""

    server_host: str = Field(alias="serverHost")
    server_port: int = Field(alias="serverPort")
    cors_allow_origins: list[str] = Field(alias="corsAllowOrigins")
    scheduler_concurrency: int = Field(alias="schedulerConcurrency")
    scheduler_queue_max_size: int = Field(alias="schedulerQueueMaxSize")
    scheduler_shutdown_timeout_seconds: float = Field(alias="schedulerShutdownTimeoutSeconds")
    events_history_limit: int = Field(alias="eventsHistoryLimit")
    events_subscriber_queue_size: int = Field(alias="eventsSubscriberQueueSize")
    model_configs_count: int = Field(default=0, alias="modelConfigsCount")
    default_model_config_id: str | None = Field(default=None, alias="defaultModelConfigId")
