"""分析执行 API Schema — 摘要、端点到诊断的完整响应模型集合。"""

from __future__ import annotations

from pydantic import Field

from argus_py.analysis.enums import (
    AnalysisRunStatus,
    CompletenessStatus,
    QualityIssueCode,
    QualityIssueLevel,
)
from argus_py.api.schemas.base import ApiModel

# ════════════════════════════════════════════════════════════════
# 通用结构
# ════════════════════════════════════════════════════════════════


class SourceLocationResponse(ApiModel):
    """源码位置（统一结构，Endpoint/CallNode/Finding 复用）。"""

    file_path: str = Field(alias="filePath")
    start_line: int = Field(alias="startLine")
    start_column: int | None = Field(default=None, alias="startColumn")
    end_line: int | None = Field(default=None, alias="endLine")
    end_column: int | None = Field(default=None, alias="endColumn")


class QualityIssueResponse(ApiModel):
    """结构化质量问题（错误码，非自然语言）。"""

    code: QualityIssueCode
    level: QualityIssueLevel
    message: str
    affected_count: int | None = Field(default=None, alias="affectedCount")
    total_count: int | None = Field(default=None, alias="totalCount")


class CompletenessMetricsResponse(ApiModel):
    """完整性指标。"""

    eligible_source_files: int = Field(alias="eligibleSourceFiles")
    parsed_source_files: int = Field(alias="parsedSourceFiles")
    total_calls: int = Field(alias="totalCalls")
    resolved_calls: int = Field(alias="resolvedCalls")


class CompletenessResponse(ApiModel):
    """完整性结论（后端计算，前端只展示）。"""

    status: CompletenessStatus
    issues: list[QualityIssueResponse] = Field(default_factory=list)
    metrics: CompletenessMetricsResponse


# ════════════════════════════════════════════════════════════════
# 分析执行摘要
# ════════════════════════════════════════════════════════════════


class AnalysisRunSummaryResponse(ApiModel):
    """单次分析执行摘要（不含子资源详情）。"""

    analysis_id: str = Field(alias="analysisId")
    task_id: str = Field(alias="taskId")
    source_snapshot_id: str = Field(alias="sourceSnapshotId")
    resolved_commit_sha: str | None = Field(default=None, alias="resolvedCommitSha")
    run_status: AnalysisRunStatus = Field(alias="runStatus")
    external_job_id: str | None = Field(default=None, alias="externalJobId")
    external_job_status: str | None = Field(default=None, alias="externalJobStatus")
    failure_code: str | None = Field(default=None, alias="failureCode")
    failure_message: str | None = Field(default=None, alias="failureMessage")
    stop_reason: str | None = Field(default=None, alias="stopReason")
    completeness: CompletenessResponse
    endpoint_count: int = Field(alias="endpointCount")
    call_graph_node_count: int = Field(alias="callGraphNodeCount")
    execution_flow_count: int = Field(alias="executionFlowCount")
    cluster_count: int = Field(alias="clusterCount")
    finding_count: int = Field(alias="findingCount")
    finding_severity_counts: dict[str, int] = Field(
        default_factory=dict, alias="findingSeverityCounts"
    )
    created_at: str = Field(alias="createdAt")
    started_at: str | None = Field(default=None, alias="startedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")
    projection_completed_at: str | None = Field(default=None, alias="projectionCompletedAt")


class AnalysisRunListResponse(ApiModel):
    """分析执行列表。"""

    items: list[AnalysisRunSummaryResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    total: int | None = None
    has_more: bool = Field(alias="hasMore")


# ════════════════════════════════════════════════════════════════
# 端点
# ════════════════════════════════════════════════════════════════


class EndpointResponse(ApiModel):
    """白盒端点信息。"""

    endpoint_id: str = Field(alias="endpointId")
    endpoint_fingerprint: str = Field(alias="endpointFingerprint")
    analysis_id: str = Field(alias="analysisId")
    source_snapshot_id: str | None = Field(default=None, alias="sourceSnapshotId")
    http_method: str = Field(alias="httpMethod")
    normalized_path: str = Field(alias="normalizedPath")
    normalized_path_template: str = Field(alias="normalizedPathTemplate")
    is_templated: bool = Field(alias="isTemplated")
    path_segment_count: int = Field(alias="pathSegmentCount")
    controller_class: str | None = Field(default=None, alias="controllerClass")
    controller_method: str | None = Field(default=None, alias="controllerMethod")
    parameters: list[str] = Field(default_factory=list)
    return_type: str | None = Field(default=None, alias="returnType")
    source_location: SourceLocationResponse | None = Field(default=None, alias="sourceLocation")
    entry_call_node_id: str | None = Field(default=None, alias="entryCallNodeId")


class EndpointPageResponse(ApiModel):
    items: list[EndpointResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    total: int | None = None
    has_more: bool = Field(alias="hasMore")


# ════════════════════════════════════════════════════════════════
# 调用图
# ════════════════════════════════════════════════════════════════


class CallNodeResponse(ApiModel):
    """调用图节点。"""

    call_node_id: str = Field(alias="callNodeId")
    call_node_fingerprint: str = Field(alias="callNodeFingerprint")
    class_name: str = Field(alias="className")
    method_name: str = Field(alias="methodName")
    method_signature: str | None = Field(default=None, alias="methodSignature")
    source_location: SourceLocationResponse | None = Field(default=None, alias="sourceLocation")
    callee_count: int = Field(alias="calleeCount")


class CallEdgeResponse(ApiModel):
    """调用图边。"""

    call_edge_id: str = Field(alias="callEdgeId")
    from_node_id: str = Field(alias="fromNodeId")
    to_node_id: str = Field(alias="toNodeId")
    to_class_name: str | None = Field(default=None, alias="toClassName")
    to_method_name: str | None = Field(default=None, alias="toMethodName")
    resolution_type: str = Field(alias="resolutionType")
    confidence: str | None = None
    source_location: SourceLocationResponse | None = Field(default=None, alias="sourceLocation")


class CallGraphPageResponse(ApiModel):
    items: list[CallEdgeResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    total: int | None = None
    has_more: bool = Field(alias="hasMore")


class CallNodePageResponse(ApiModel):
    items: list[CallNodeResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    total: int | None = None
    has_more: bool = Field(alias="hasMore")


# ════════════════════════════════════════════════════════════════
# 执行流
# ════════════════════════════════════════════════════════════════


class ExecutionFlowStepResponse(ApiModel):
    """执行流步骤。"""

    flow_step_id: str = Field(alias="flowStepId")
    step_index: int = Field(alias="stepIndex")
    depth: int
    method_key: str = Field(alias="methodKey")
    class_name: str | None = Field(default=None, alias="className")
    method_name: str | None = Field(default=None, alias="methodName")
    call_node_id: str | None = Field(default=None, alias="callNodeId")


class ExecutionFlowResponse(ApiModel):
    """执行流。"""

    execution_flow_id: str = Field(alias="executionFlowId")
    entry_point: str = Field(alias="entryPoint")
    call_depth: int = Field(alias="callDepth")
    steps: list[ExecutionFlowStepResponse] = Field(default_factory=list)


class ExecutionFlowPageResponse(ApiModel):
    items: list[ExecutionFlowResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    total: int | None = None
    has_more: bool = Field(alias="hasMore")


# ════════════════════════════════════════════════════════════════
# 诊断
# ════════════════════════════════════════════════════════════════


class DiagnosticsResponse(ApiModel):
    """白盒诊断信息。注意：completeness 结论不在此处，在摘要接口。"""

    total_source_files: int = Field(alias="totalSourceFiles")
    eligible_source_files: int = Field(alias="eligibleSourceFiles")
    parsed_file_count: int = Field(alias="parsedFileCount")
    failed_file_count: int = Field(alias="failedFileCount")
    failed_files: list[str] = Field(default_factory=list, alias="failedFiles")
    total_calls: int = Field(alias="totalCalls")
    resolved_high: int = Field(alias="resolvedHigh")
    resolved_medium: int = Field(alias="resolvedMedium")
    resolved_low: int = Field(alias="resolvedLow")
    unresolved: int
    classpath_available: bool = Field(alias="classpathAvailable")
    jar_count: int = Field(alias="jarCount")
    classpath_source: str | None = Field(default=None, alias="classpathSource")
    classpath_warnings: list[str] = Field(default_factory=list, alias="classpathWarnings")
    classpath_errors: list[str] = Field(default_factory=list, alias="classpathErrors")
    module_count: int = Field(alias="moduleCount")
    application_module_count: int = Field(alias="applicationModuleCount")
