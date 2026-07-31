"""黑白盒关联 API Schema — CorrelationRun, Evidence, Summary 响应模型。"""

from __future__ import annotations

from pydantic import Field

from argus_py.api.schemas.analysis import (
    EndpointResponse,
    ExecutionFlowResponse,
    FindingDetailResponse,
)
from argus_py.api.schemas.base import ApiModel

# ════════════════════════════════════════════════════════════════
# 通用
# ════════════════════════════════════════════════════════════════


class CorrelationRunResponse(ApiModel):
    """关联运行详情。"""

    correlation_run_id: str = Field(alias="correlationRunId")
    project_id: str = Field(alias="projectId")
    blackbox_run_id: str = Field(alias="blackboxRunId")
    desired_source_snapshot_id: str = Field(alias="desiredSourceSnapshotId")
    desired_analysis_config_digest: str = Field(alias="desiredAnalysisConfigDigest")
    required_analyzer_version: str = Field(alias="requiredAnalyzerVersion")
    allow_partial_analysis: bool = Field(alias="allowPartialAnalysis")
    analysis_id: str | None = Field(default=None, alias="analysisId")
    bound_source_snapshot_id: str | None = Field(default=None, alias="boundSourceSnapshotId")
    analysis_projection_version: int | None = Field(default=None, alias="analysisProjectionVersion")
    correlation_config_digest: str = Field(alias="correlationConfigDigest")
    matcher_version: str = Field(alias="matcherVersion")
    normalization_version: str = Field(alias="normalizationVersion")
    supersedes_correlation_run_id: str | None = Field(
        default=None, alias="supersedesCorrelationRunId"
    )
    source_alignment_status: str = Field(alias="sourceAlignmentStatus")
    status: str
    active_attempt_id: str | None = Field(default=None, alias="activeAttemptId")
    source_mismatch_overridden: bool = Field(alias="sourceMismatchOverridden")
    source_mismatch_override_by: str | None = Field(default=None, alias="sourceMismatchOverrideBy")
    source_mismatch_override_at: str | None = Field(default=None, alias="sourceMismatchOverrideAt")
    source_mismatch_override_reason: str | None = Field(
        default=None, alias="sourceMismatchOverrideReason"
    )
    started_at: str | None = Field(default=None, alias="startedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")
    error_code: str | None = Field(default=None, alias="errorCode")
    error_message: str | None = Field(default=None, alias="errorMessage")
    created_at: str = Field(alias="createdAt")


class CorrelationAttemptResponse(ApiModel):
    """关联尝试详情。"""

    correlation_attempt_id: str = Field(alias="correlationAttemptId")
    correlation_run_id: str = Field(alias="correlationRunId")
    attempt_number: int = Field(alias="attemptNumber")
    status: str
    evidence_completeness: str = Field(alias="evidenceCompleteness")
    lease_owner: str | None = Field(default=None, alias="leaseOwner")
    started_at: str = Field(alias="startedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")
    error_code: str | None = Field(default=None, alias="errorCode")
    error_message: str | None = Field(default=None, alias="errorMessage")
    created_at: str = Field(alias="createdAt")


class CorrelationAttemptListResponse(ApiModel):
    """关联尝试列表。"""

    items: list[CorrelationAttemptResponse]
    total: int


# ════════════════════════════════════════════════════════════════
# HTTP 请求证据
# ════════════════════════════════════════════════════════════════


class HttpRequestEvidenceResponse(ApiModel):
    """黑盒 HTTP 请求证据（不暴露 normalized_path、request_headers_json）。"""

    request_evidence_id: str = Field(alias="requestEvidenceId")
    blackbox_run_id: str = Field(alias="blackboxRunId")
    task_id: str = Field(alias="taskId")
    step_execution_id: str | None = Field(default=None, alias="stepExecutionId")
    step_attempt: int = Field(alias="stepAttempt")
    request_sequence: int = Field(alias="requestSequence")
    http_method: str = Field(alias="httpMethod")
    display_path: str = Field(alias="displayPath")
    origin: str
    resource_type: str = Field(alias="resourceType")
    endpoint_match_eligibility: str = Field(alias="endpointMatchEligibility")
    response_status: int | None = Field(default=None, alias="responseStatus")
    outcome: str
    request_owner: str = Field(alias="requestOwner")
    response_from_service_worker: bool = Field(alias="responseFromServiceWorker")
    page_sequence: int = Field(alias="pageSequence")
    captured_at: str = Field(alias="capturedAt")
    finished_at: str | None = Field(default=None, alias="finishedAt")


class HttpRequestEvidencePageResponse(ApiModel):
    items: list[HttpRequestEvidenceResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    total: int | None = None
    has_more: bool = Field(alias="hasMore")


# ════════════════════════════════════════════════════════════════
# 端点证据
# ════════════════════════════════════════════════════════════════


class EndpointEvidenceCandidateResponse(ApiModel):
    """候选端点。"""

    endpoint_id: str = Field(alias="endpointId")
    candidate_rank: int = Field(alias="candidateRank")
    match_strategy: str = Field(alias="matchStrategy")
    confidence: str
    reason_code: str = Field(alias="reasonCode")
    selected: bool


class EndpointEvidenceResponse(ApiModel):
    """请求与白盒端点的匹配证据。"""

    endpoint_evidence_id: str = Field(alias="endpointEvidenceId")
    correlation_attempt_id: str = Field(alias="correlationAttemptId")
    request_evidence_id: str = Field(alias="requestEvidenceId")
    resolution_status: str = Field(alias="resolutionStatus")
    match_strategy: str = Field(alias="matchStrategy")
    confidence: str
    matched_endpoint_id: str | None = Field(default=None, alias="matchedEndpointId")
    matched_endpoint_info: EndpointResponse | None = Field(
        default=None, alias="matchedEndpointInfo"
    )
    match_reason_code: str = Field(alias="matchReasonCode")
    candidate_count: int = Field(alias="candidateCount")
    # 反规范化字段（JOIN 获得）
    http_method: str | None = Field(default=None, alias="httpMethod")
    request_path: str | None = Field(default=None, alias="requestPath")
    display_path: str | None = Field(default=None, alias="displayPath")
    origin: str | None = None
    resource_type: str | None = Field(default=None, alias="resourceType")
    candidates: list[EndpointEvidenceCandidateResponse] = Field(default_factory=list)
    execution_flows: list[ExecutionFlowResponse] = Field(default_factory=list)


class EndpointEvidencePageResponse(ApiModel):
    items: list[EndpointEvidenceResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    total: int | None = None
    has_more: bool = Field(alias="hasMore")


# ════════════════════════════════════════════════════════════════
# Finding 关联
# ════════════════════════════════════════════════════════════════


class FindingEvidenceResponse(ApiModel):
    """Finding 关联证据。"""

    finding_evidence_id: str = Field(alias="findingEvidenceId")
    correlation_attempt_id: str = Field(alias="correlationAttemptId")
    finding_id: str = Field(alias="findingId")
    finding_info: FindingDetailResponse | None = Field(default=None, alias="findingInfo")
    best_relation_type: str = Field(alias="bestRelationType")
    minimum_call_distance: int | None = Field(default=None, alias="minimumCallDistance")
    confirmed_request_count: int = Field(alias="confirmedRequestCount")
    candidate_request_count: int = Field(alias="candidateRequestCount")


class FindingEvidencePageResponse(ApiModel):
    items: list[FindingEvidenceResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    total: int | None = None
    has_more: bool = Field(alias="hasMore")


# ════════════════════════════════════════════════════════════════
# 采集质量
# ════════════════════════════════════════════════════════════════


class CaptureQualityResponse(ApiModel):
    """采集质量统计。"""

    blackbox_run_id: str = Field(alias="blackboxRunId")
    total_observed: int = Field(alias="totalObserved")
    accepted_started: int = Field(alias="acceptedStarted")
    persisted_count: int = Field(alias="persistedCount")
    filtered_by_resource_type: int = Field(alias="filteredByResourceType")
    filtered_cross_origin: int = Field(alias="filteredCrossOrigin")
    filtered_by_method: int = Field(alias="filteredByMethod")
    filtered_websocket_count: int = Field(alias="filteredWebsocketCount")
    filtered_path_too_long: int = Field(alias="filteredPathTooLong")
    dropped_pending_limit: int = Field(alias="droppedPendingLimit")
    dropped_run_limit: int = Field(alias="droppedRunLimit")
    dropped_writer_queue_limit: int = Field(alias="droppedWriterQueueLimit")
    writer_retry_count: int = Field(alias="writerRetryCount")
    writer_failed_batch_count: int = Field(alias="writerFailedBatchCount")
    persistence_failed: int = Field(alias="persistenceFailed")
    truncated: bool
    truncation_reason: str | None = Field(default=None, alias="truncationReason")


# ════════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════════


class CorrelationSummaryResponse(ApiModel):
    """关联汇总指标。"""

    correlation_run_id: str = Field(alias="correlationRunId")
    status: str
    source_alignment_status: str = Field(alias="sourceAlignmentStatus")

    # 请求级
    captured_request_count: int = Field(alias="capturedRequestCount")
    correlatable_request_count: int = Field(alias="correlatableRequestCount")
    confirmed_matched_request_count: int = Field(alias="confirmedMatchedRequestCount")
    ambiguous_request_count: int = Field(alias="ambiguousRequestCount")
    method_mismatch_candidate_count: int = Field(alias="methodMismatchCandidateCount")
    unmatched_request_count: int = Field(alias="unmatchedRequestCount")

    # 端点级
    total_endpoint_count: int = Field(alias="totalEndpointCount")
    confirmed_touched_endpoint_count: int = Field(alias="confirmedTouchedEndpointCount")
    candidate_touched_endpoint_count: int = Field(alias="candidateTouchedEndpointCount")
    uncovered_endpoint_count: int = Field(alias="uncoveredEndpointCount")
    attempted_evidence_count: int = Field(alias="attemptedEvidenceCount")

    # Finding 级
    total_finding_count: int = Field(alias="totalFindingCount")
    confirmed_related_finding_count: int = Field(alias="confirmedRelatedFindingCount")
    candidate_related_finding_count: int = Field(alias="candidateRelatedFindingCount")
    unrelated_finding_count: int = Field(alias="unrelatedFindingCount")

    # 质量
    cross_origin_filtered_count: int = Field(alias="crossOriginFilteredCount")
    resource_filtered_count: int = Field(alias="resourceFilteredCount")
    dropped_request_count: int = Field(alias="droppedRequestCount")
    failed_capture_count: int = Field(alias="failedCaptureCount")
    evidence_completeness: str = Field(alias="evidenceCompleteness")
    matcher_version: str = Field(alias="matcherVersion")
    normalization_version: str = Field(alias="normalizationVersion")


# ════════════════════════════════════════════════════════════════
# 操作请求
# ════════════════════════════════════════════════════════════════


class BindAnalysisRequest(ApiModel):
    """绑定白盒分析请求。"""

    analysis_id: str = Field(alias="analysisId")
    expected_projection_version: int | None = Field(default=None, alias="expectedProjectionVersion")
    source_mismatch_override: bool = Field(default=False, alias="sourceMismatchOverride")
    source_mismatch_override_reason: str | None = Field(
        default=None, alias="sourceMismatchOverrideReason"
    )


# ════════════════════════════════════════════════════════════════
# Uncovered Endpoints
# ════════════════════════════════════════════════════════════════


class UncoveredEndpointPageResponse(ApiModel):
    """未被触达的白盒端点分页响应（复用 EndpointResponse）。"""

    items: list[EndpointResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    total: int | None = None
    has_more: bool = Field(alias="hasMore")
