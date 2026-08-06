from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator

from argus_py.api.schemas.analysis import AnalysisRunSummaryResponse
from argus_py.api.schemas.base import ApiModel, blank_to_none, strip_text
from argus_py.core.enums import FindingSeverity, FindingType, StepResult, TaskStatus, TaskType
from argus_py.redaction import (
    redact_finding_entry,
    redact_href,
    redact_log_entry,
    redact_sensitive_text,
    redact_step_params,
)
from argus_py.task.models import Finding, Task, TaskLog
from argus_py.whitebox.config import ClasspathMode, SourceType, WhiteboxTaskConfig


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
        return cls.model_validate(redact_log_entry(dict(log.__dict__)))


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
    rule_id: str | None = Field(default=None, alias="ruleId")
    rule_category: str | None = Field(default=None, alias="ruleCategory")
    confidence: str | None = None
    fingerprint: str | None = None
    snippet: str | None = None
    analysis_id: str | None = Field(default=None, alias="analysisId")

    @classmethod
    def from_finding(cls, finding: Finding) -> "FindingResponse":
        """从问题实体转换响应模型。"""
        return cls.model_validate(redact_finding_entry(dict(finding.__dict__)))


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
    whitebox_config: WhiteboxTaskConfig | None = Field(default=None, alias="whiteboxConfig")

    @field_validator("goal", "project_id", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        """必填文本去掉两端空白后再校验。"""
        return strip_text(value)

    @field_validator("start_url", mode="before")
    @classmethod
    def strip_start_url(cls, value: object) -> object:
        """start_url 去掉两端空白；白盒任务不要求必填。"""
        return strip_text(value) if value is not None else None

    @field_validator("name", "start_url", "model_config_id", mode="before")
    @classmethod
    def blank_optional_text_to_none(cls, value: object) -> object:
        """空白可选文本统一视为未填写。"""
        return blank_to_none(value)

    @field_validator("whitebox_config", mode="before")
    @classmethod
    def parse_whitebox_config(cls, value: object) -> object:
        """将 whiteboxConfig dict 解析为 WhiteboxTaskConfig。"""
        if value is None or isinstance(value, WhiteboxTaskConfig):
            return value
        if isinstance(value, dict):
            return WhiteboxTaskConfig.model_validate(value)
        return value

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

    @model_validator(mode="after")
    def validate_by_task_type(self) -> "TaskCreateRequest":
        """按任务类型校验。

        白盒任务：whiteboxConfig 或 parameters 中必须提供源码信息。
        新旧配置不能同时存在。
        """
        from argus_py.whitebox.config import LEGACY_WHITEBOX_PARAM_KEYS

        is_wb = self.task_type == TaskType.WHITEBOX
        has_config = self.whitebox_config is not None
        legacy_keys_present = LEGACY_WHITEBOX_PARAM_KEYS & set((self.parameters or {}).keys())

        if is_wb and has_config and legacy_keys_present:
            raise ValueError(
                f"whiteboxConfig 与 parameters 中的白盒字段不能同时提供。"
                f"冲突字段: {', '.join(sorted(legacy_keys_present))}"
            )
        if is_wb and not has_config and not legacy_keys_present:
            raise ValueError("白盒任务必须提供 whiteboxConfig 或 parameters.repo_url / source_path")
        if not is_wb and has_config:
            raise ValueError("非白盒任务不能提供 whiteboxConfig")
        return self


class TaskUpdateRequest(TaskCreateRequest):
    """更新任务基础信息请求。"""


# ════════════════════════════════════════════════
# 白盒配置响应模型（脱敏展示）
# ════════════════════════════════════════════════


class ConfigStatus(str, Enum):
    """白盒配置反序列化状态。"""

    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class MavenConfigResponse(ApiModel):
    """Maven 配置响应 — 展示级脱敏（布尔标记）+ 编辑级真实值。"""

    # 展示级
    settings_configured: bool = Field(alias="settingsConfigured")
    local_repo_configured: bool = Field(alias="localRepoConfigured")
    executable_configured: bool = Field(alias="executableConfigured")
    classpath_mode: ClasspathMode = Field(alias="classpathMode")
    offline: bool
    auto_detect: bool = Field(alias="autoDetect")
    # 编辑级真实值（用户编辑表单时需要看到完整路径）
    settings_xml: str | None = Field(default=None, alias="settingsXml")
    local_repository: str | None = Field(default=None, alias="localRepository")
    executable: str | None = None
    classpath_file: str | None = Field(default=None, alias="classpathFile")
    generate_classpath: bool = Field(default=True, alias="generateClasspath")
    offline_timeout_seconds: int | None = Field(default=None, alias="offlineTimeoutSeconds")
    online_timeout_seconds: int | None = Field(default=None, alias="onlineTimeoutSeconds")
    prepare_reactor_artifacts: bool = Field(default=False, alias="prepareReactorArtifacts")


class WhiteboxTaskConfigResponse(ApiModel):
    """白盒配置响应（展示级脱敏 + 编辑级真实值）。"""

    source_type: SourceType = Field(alias="sourceType")
    # 展示级
    repo_url_display: str | None = Field(default=None, alias="repoUrlDisplay")
    source_path_display: str | None = Field(default=None, alias="sourcePathDisplay")
    source_path_configured: bool = Field(alias="sourcePathConfigured")
    # 编辑级真实值
    repo_url: str | None = Field(default=None, alias="repoUrl")
    source_path: str | None = Field(default=None, alias="sourcePath")
    ref: str | None = None
    scope: str = "all"
    target_modules: list[str] = Field(default_factory=list, alias="targetModules")
    maven: MavenConfigResponse | None = None


class WhiteboxConfigViewResponse(ApiModel):
    """白盒配置视图 — 包装反序列化状态。"""

    status: ConfigStatus = ConfigStatus.VALID
    config: WhiteboxTaskConfigResponse | None = None
    error_code: str | None = Field(default=None, alias="errorCode")


def _build_whitebox_config_view(task: Task) -> dict[str, Any] | None:
    """从 Task 实体构造脱敏白盒配置视图。

    同时返回展示级脱敏值（display）和编辑级真实值，供不同 UI 场景使用：
    - Display: sourcePathDisplay / repoUrlDisplay — TaskDetail 详情展示
    - Edit: sourcePath / repoUrl — TaskFormDialog 编辑表单回填
    """
    if task.task_type != TaskType.WHITEBOX:
        return None
    raw = task.whitebox_config_json
    if not raw:
        return {"status": ConfigStatus.UNKNOWN, "config": None, "errorCode": None}
    try:
        data = json.loads(raw)
    except Exception:
        return {"status": ConfigStatus.INVALID, "config": None, "errorCode": "PARSE_ERROR"}
    source_path = data.get("source_path")
    return {
        "status": ConfigStatus.VALID,
        "config": {
            "sourceType": data.get("source_type") or "local",
            # 展示级
            "repoUrlDisplay": (
                _redact_repo_url(task.source_repo_url) if task.source_repo_url else None
            ),
            "sourcePathDisplay": (_redact_path(source_path) if source_path else None),
            "sourcePathConfigured": bool(source_path),
            # 编辑级真实值
            # 主路径走 task.source_repo_url（已脱敏但可编辑回填）；
            # 兜底读取持久化 JSON 的 clone_url（to_persisted() 实际写入的键，旧 repo_url 键恒为 None）。
            "repoUrl": task.source_repo_url or data.get("clone_url"),
            "sourcePath": source_path,
            "ref": data.get("ref"),
            "scope": data.get("scope", "all"),
            "targetModules": data.get("target_modules", []),
            "maven": _build_maven_config_view(data.get("maven", {})),
        },
        "errorCode": None,
    }


def _build_maven_config_view(maven: dict[str, Any]) -> dict[str, Any]:
    return {
        # 展示级
        "settingsConfigured": bool(maven.get("settings_xml")),
        "localRepoConfigured": bool(maven.get("local_repository")),
        "executableConfigured": bool(maven.get("executable")),
        "classpathMode": maven.get("classpath_mode", "AUTO"),
        "offline": bool(maven.get("offline", False)),
        "autoDetect": maven.get("auto_detect", True),
        # 编辑级真实值
        "settingsXml": maven.get("settings_xml"),
        "localRepository": maven.get("local_repository"),
        "executable": maven.get("executable"),
        "classpathFile": maven.get("classpath_file"),
        "generateClasspath": maven.get("generate_classpath", True),
        "offlineTimeoutSeconds": maven.get("offline_timeout_seconds"),
        "onlineTimeoutSeconds": maven.get("online_timeout_seconds"),
        "prepareReactorArtifacts": maven.get("prepare_reactor_artifacts", False),
    }


def _redact_repo_url(url: str | None) -> str | None:
    """仓库 URL 脱敏。

    ``task.source_repo_url`` 已由 SourceResolver 在保存时脱敏（移除凭据），
    此函数作为预留扩展点 — 若后续需要更严格的展示级脱敏（如截断域名），
    在此处追加处理。
    """
    if not url:
        return None
    return url


def _redact_path(path: str | None) -> str | None:
    if not path:
        return None
    parts = path.replace("\\", "/").rstrip("/").split("/")
    if len(parts) <= 2:
        return path
    return f".../{'/'.join(parts[-2:])}"


class _TaskResponseBase(ApiModel):
    """`TaskResponse` / `TaskSummaryResponse` 共享字段与转换逻辑。

    收敛了 18 个公共字段以及统一的脱敏规则；子类只需要声明各自的差异字段
    （TaskResponse: logs/findings；TaskSummaryResponse: finding_count）并
    在 ``from_task`` 里补齐对应 kwargs。
    """

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
    created_at: datetime = Field(alias="createdAt")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")
    report_path: str | None = Field(default=None, alias="reportPath")
    result_summary: str | None = Field(default=None, alias="resultSummary")
    error_message: str | None = Field(default=None, alias="errorMessage")
    execution_attempt: int = Field(alias="executionAttempt", ge=1)
    # 白盒扩展字段
    whitebox_config_view: WhiteboxConfigViewResponse | None = Field(
        default=None, alias="whiteboxConfigView"
    )
    latest_analysis_run: AnalysisRunSummaryResponse | None = Field(
        default=None, alias="latestAnalysisRun"
    )

    @staticmethod
    def _common_fields(task: Task, scheduler_status: str | None) -> dict[str, Any]:
        """构造共享字段 kwargs（含脱敏处理），子类负责补齐差异字段。"""
        return {
            "task_id": task.task_id,
            "project_id": task.project_id,
            "goal": redact_sensitive_text(task.goal),
            "name": task.name,
            "start_url": redact_href(task.start_url) if task.start_url else None,
            "task_type": task.task_type,
            "status": task.status,
            "scheduler_status": scheduler_status,
            "max_steps": task.max_steps,
            "timeout_seconds": task.timeout_seconds,
            "capture_screenshots": task.capture_screenshots,
            "current_step": task.current_step,
            "parameters": redact_step_params(task.parameters),
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "report_path": Path(task.report_path).name if task.report_path else None,
            "result_summary": (
                redact_sensitive_text(task.result_summary) if task.result_summary else None
            ),
            "error_message": (
                redact_sensitive_text(task.error_message) if task.error_message else None
            ),
            "execution_attempt": task.execution_attempt,
            "whitebox_config_view": _build_whitebox_config_view(task),
            "latest_analysis_run": None,
        }


class TaskResponse(_TaskResponseBase):
    """任务详情响应（含步骤日志和发现项）。"""

    logs: list[TaskLogResponse]
    findings: list[FindingResponse]

    @classmethod
    def from_task(cls, task: Task, scheduler_status: str | None = None) -> "TaskResponse":
        """从任务实体转换响应模型。"""
        return cls(
            **cls._common_fields(task, scheduler_status),
            logs=[TaskLogResponse.from_task_log(log) for log in task.logs],
            findings=[FindingResponse.from_finding(finding) for finding in task.findings],
        )


class TaskListResponse(ApiModel):
    """任务列表响应。"""

    total: int
    tasks: list[TaskResponse]


class TaskSummaryResponse(_TaskResponseBase):
    """轻量任务响应（不含日志和发现项），供列表页使用。"""

    finding_count: int = Field(alias="findingCount")

    @classmethod
    def from_task(cls, task: Task, scheduler_status: str | None = None) -> "TaskSummaryResponse":
        """从任务实体转换摘要响应。"""
        return cls(
            **cls._common_fields(task, scheduler_status),
            finding_count=task.finding_count,
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


class DashboardStatsResponse(ApiModel):
    """仪表盘聚合统计响应。

    与 ``GET /tasks`` 的分页列表解耦：``tasks_total`` / ``running_total`` 走 COUNT，
    不受当前页 ``limit`` 影响；``recent_tasks`` 单独返回最近 N 条 summary。
    """

    tasks_total: int = Field(alias="tasksTotal")
    running_total: int = Field(alias="runningTotal")
    findings_total: int = Field(alias="findingsTotal")
    recent_tasks: list[TaskSummaryResponse] = Field(default_factory=list, alias="recentTasks")
