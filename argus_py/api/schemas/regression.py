"""回归测试闭环 API 请求/响应模型（camelCase wire contract）。"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from argus_py.api.schemas.base import ApiModel


class RegressionCaseCreateRequest(ApiModel):
    """创建回归用例。

    ``parameters`` 中的 model_config_id / prompt_extensions / 白盒源码输入等
    与任务创建接口语义一致；保存时按同一套规则校验并合并项目默认值。
    """

    name: str = Field(min_length=1, max_length=200)
    task_type: str = Field(default="blackbox", alias="taskType")
    goal: str = Field(min_length=1)
    start_url: str | None = Field(default=None, alias="startUrl")
    max_steps: int | None = Field(default=None, alias="maxSteps", ge=1)
    timeout_seconds: int | None = Field(default=None, alias="timeoutSeconds", ge=1)
    capture_screenshots: bool | None = Field(default=None, alias="captureScreenshots")
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    display_order: int = Field(default=0, alias="displayOrder")


class RegressionCaseUpdateRequest(ApiModel):
    """更新回归用例（部分更新；taskType 不允许变更）。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str | None = Field(default=None, min_length=1)
    start_url: str | None = Field(default=None, alias="startUrl")
    max_steps: int | None = Field(default=None, alias="maxSteps", ge=1)
    timeout_seconds: int | None = Field(default=None, alias="timeoutSeconds", ge=1)
    capture_screenshots: bool | None = Field(default=None, alias="captureScreenshots")
    parameters: dict[str, Any] | None = None
    enabled: bool | None = None
    display_order: int | None = Field(default=None, alias="displayOrder")


class RegressionCaseResponse(ApiModel):
    """回归用例。"""

    case_id: str = Field(alias="caseId")
    project_id: str = Field(alias="projectId")
    name: str
    task_type: str = Field(alias="taskType")
    goal: str
    start_url: str | None = Field(alias="startUrl")
    max_steps: int = Field(alias="maxSteps")
    timeout_seconds: int = Field(alias="timeoutSeconds")
    capture_screenshots: bool = Field(alias="captureScreenshots")
    parameters: dict[str, Any]
    whitebox_config_json: str | None = Field(
        default=None,
        alias="whiteboxConfigJson",
        description="白盒配置 JSON 快照；黑盒用例为 null",
    )
    enabled: bool
    display_order: int = Field(alias="displayOrder")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")

    @classmethod
    def from_case(cls, case: Any) -> "RegressionCaseResponse":
        import json

        try:
            parameters = json.loads(case.parameters_json)
        except (TypeError, ValueError):
            parameters = {}
        if not isinstance(parameters, dict):
            parameters = {}
        return cls(
            case_id=case.case_id,
            project_id=case.project_id,
            name=case.name,
            task_type=case.task_type.value,
            goal=case.goal,
            start_url=case.start_url,
            max_steps=case.max_steps,
            timeout_seconds=case.timeout_seconds,
            capture_screenshots=case.capture_screenshots,
            parameters=parameters,
            whitebox_config_json=case.whitebox_config_json,
            enabled=case.enabled,
            display_order=case.display_order,
            created_at=case.created_at,
            updated_at=case.updated_at,
        )


class RegressionCaseListResponse(ApiModel):
    """回归用例列表。"""

    total: int
    cases: list[RegressionCaseResponse]


class RegressionRunItemResponse(ApiModel):
    """回归批次项。"""

    item_id: str = Field(alias="itemId")
    run_id: str = Field(alias="runId")
    case_id: str = Field(alias="caseId")
    case_name: str = Field(alias="caseName")
    display_order: int = Field(alias="displayOrder")
    task_id: str | None = Field(alias="taskId")
    status: str
    finding_count: int | None = Field(alias="findingCount")
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")
    created_at: str = Field(alias="createdAt")
    # 实时权威状态（tasks 表），批次项状态镜像滞后时可以此为准
    task_status: str | None = Field(default=None, alias="taskStatus")


class RegressionDiffEntryResponse(ApiModel):
    """单条问题差异。"""

    category: str
    fingerprint: str
    title: str
    severity: str
    finding_type: str = Field(alias="findingType")
    location: str | None
    case_id: str | None = Field(alias="caseId")
    current_task_id: str | None = Field(alias="currentTaskId")
    baseline_task_id: str | None = Field(alias="baselineTaskId")


class RegressionRunSummaryResponse(ApiModel):
    """批次持久化汇总（终态后含差异明细与门禁原因）。"""

    fingerprint_version: str | None = Field(default=None, alias="fingerprintVersion")
    baseline_run_id: str | None = Field(default=None, alias="baselineRunId")
    gate_result: str | None = Field(default=None, alias="gateResult")
    blocking_reasons: list[str] = Field(default_factory=list, alias="blockingReasons")
    item_counts: dict[str, int] = Field(default_factory=dict, alias="itemCounts")
    finding_totals: dict[str, int] = Field(default_factory=dict, alias="findingTotals")
    diff: dict[str, Any] = Field(default_factory=dict)


class RegressionRunResponse(ApiModel):
    """回归批次。"""

    run_id: str = Field(alias="runId")
    project_id: str = Field(alias="projectId")
    trigger_source: str = Field(alias="triggerSource")
    triggered_by: str | None = Field(alias="triggeredBy")
    baseline_run_id: str | None = Field(alias="baselineRunId")
    status: str
    gate_result: str | None = Field(alias="gateResult")
    is_baseline: bool = Field(alias="isBaseline")
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")
    started_at: str | None = Field(alias="startedAt")
    completed_at: str | None = Field(alias="completedAt")
    created_at: str = Field(alias="createdAt")

    @classmethod
    def from_run(cls, run: Any) -> "RegressionRunResponse":
        return cls(
            run_id=run.run_id,
            project_id=run.project_id,
            trigger_source=run.trigger_source.value,
            triggered_by=run.triggered_by,
            baseline_run_id=run.baseline_run_id,
            status=run.status.value,
            gate_result=run.gate_result.value if run.gate_result else None,
            is_baseline=run.is_baseline,
            error_code=run.error_code,
            error_message=run.error_message,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
        )


class RegressionRunDetailResponse(ApiModel):
    """批次详情：批次本体 + 批次项 + 持久化汇总。"""

    run: RegressionRunResponse
    items: list[RegressionRunItemResponse] = Field(default_factory=list)
    summary: RegressionRunSummaryResponse = Field(default_factory=RegressionRunSummaryResponse)


class RegressionRunListResponse(ApiModel):
    """批次列表（稳定分页）。"""

    total: int
    runs: list[RegressionRunResponse]
    offset: int
    limit: int


class RegressionRunCreateRequest(ApiModel):
    """创建回归批次。"""

    triggered_by: str | None = Field(default=None, alias="triggeredBy", max_length=200)


class RegressionBaselineSetRequest(ApiModel):
    """设置项目基线。"""

    run_id: str = Field(alias="runId", min_length=1)


class RegressionBaselineResponse(ApiModel):
    """当前项目基线。"""

    baseline_run_id: str | None = Field(alias="baselineRunId")
