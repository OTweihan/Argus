"""关联实体的 API dict 转换（camelCase，供路由响应与报告聚合共用）。"""

from __future__ import annotations

from typing import Any


def correlation_run_to_dict(cr: Any) -> dict[str, Any]:
    """将 CorrelationRun 实体转为 dict（camelCase keys for API）。"""
    return {
        "correlationRunId": cr.correlation_run_id,
        "projectId": cr.project_id,
        "blackboxRunId": cr.blackbox_run_id,
        "desiredSourceSnapshotId": cr.desired_source_snapshot_id,
        "desiredAnalysisConfigDigest": cr.desired_analysis_config_digest,
        "requiredAnalyzerVersion": cr.required_analyzer_version,
        "allowPartialAnalysis": cr.allow_partial_analysis,
        "analysisId": cr.analysis_id,
        "boundSourceSnapshotId": cr.bound_source_snapshot_id,
        "analysisProjectionVersion": cr.analysis_projection_version,
        "correlationConfigDigest": cr.correlation_config_digest,
        "matcherVersion": cr.matcher_version,
        "normalizationVersion": cr.normalization_version,
        "supersedesCorrelationRunId": cr.supersedes_correlation_run_id,
        "sourceAlignmentStatus": (
            cr.source_alignment_status.value
            if hasattr(cr.source_alignment_status, "value")
            else str(cr.source_alignment_status)
        ),
        "status": cr.status.value if hasattr(cr.status, "value") else str(cr.status),
        "activeAttemptId": cr.active_attempt_id,
        "sourceMismatchOverridden": cr.source_mismatch_overridden,
        "sourceMismatchOverrideBy": cr.source_mismatch_override_by,
        "sourceMismatchOverrideAt": cr.source_mismatch_override_at,
        "sourceMismatchOverrideReason": cr.source_mismatch_override_reason,
        "startedAt": cr.started_at,
        "completedAt": cr.completed_at,
        "errorCode": cr.error_code,
        "errorMessage": cr.error_message,
        "createdAt": cr.created_at,
    }


def attempt_to_dict(a: Any) -> dict[str, Any]:
    """将 CorrelationAttempt 实体转为 dict。"""
    return {
        "correlationAttemptId": a.correlation_attempt_id,
        "correlationRunId": a.correlation_run_id,
        "attemptNumber": a.attempt_number,
        "status": a.status.value if hasattr(a.status, "value") else str(a.status),
        "evidenceCompleteness": (
            a.evidence_completeness.value
            if hasattr(a.evidence_completeness, "value")
            else str(a.evidence_completeness)
        ),
        "leaseOwner": a.lease_owner,
        "startedAt": a.started_at,
        "completedAt": a.completed_at,
        "errorCode": a.error_code,
        "errorMessage": a.error_message,
        "createdAt": a.created_at,
    }


def summary_to_dict(s: Any) -> dict[str, Any]:
    """将 CorrelationSummary 转为 dict。"""
    if s is None:
        return {}
    return {
        "correlationRunId": s.correlation_run_id,
        "status": s.status,
        "sourceAlignmentStatus": s.source_alignment_status,
        "capturedRequestCount": s.captured_request_count,
        "correlatableRequestCount": s.correlatable_request_count,
        "confirmedMatchedRequestCount": s.confirmed_matched_request_count,
        "ambiguousRequestCount": s.ambiguous_request_count,
        "methodMismatchCandidateCount": s.method_mismatch_candidate_count,
        "unmatchedRequestCount": s.unmatched_request_count,
        "totalEndpointCount": s.total_endpoint_count,
        "confirmedTouchedEndpointCount": s.confirmed_touched_endpoint_count,
        "candidateTouchedEndpointCount": s.candidate_touched_endpoint_count,
        "uncoveredEndpointCount": s.uncovered_endpoint_count,
        "attemptedEvidenceCount": s.attempted_evidence_count,
        "totalFindingCount": s.total_finding_count,
        "confirmedRelatedFindingCount": s.confirmed_related_finding_count,
        "candidateRelatedFindingCount": s.candidate_related_finding_count,
        "unrelatedFindingCount": s.unrelated_finding_count,
        "crossOriginFilteredCount": s.cross_origin_filtered_count,
        "resourceFilteredCount": s.resource_filtered_count,
        "droppedRequestCount": s.dropped_request_count,
        "failedCaptureCount": s.failed_capture_count,
        "evidenceCompleteness": s.evidence_completeness,
        "matcherVersion": s.matcher_version,
        "normalizationVersion": s.normalization_version,
    }


def http_request_to_dict(req: Any) -> dict[str, Any]:
    """将 HttpRequestEvidence 实体转为 dict。"""
    return {
        "requestEvidenceId": req.request_evidence_id,
        "blackboxRunId": req.blackbox_run_id,
        "taskId": req.task_id,
        "stepExecutionId": req.step_execution_id,
        "stepAttempt": req.step_attempt,
        "requestSequence": req.request_sequence,
        "httpMethod": req.http_method,
        "displayPath": req.display_path,
        "origin": req.origin,
        "resourceType": req.resource_type,
        "endpointMatchEligibility": (
            req.endpoint_match_eligibility.value
            if hasattr(req.endpoint_match_eligibility, "value")
            else str(req.endpoint_match_eligibility)
        ),
        "responseStatus": req.response_status,
        "outcome": req.outcome.value if hasattr(req.outcome, "value") else str(req.outcome),
        "requestOwner": (
            req.request_owner.value
            if hasattr(req.request_owner, "value")
            else str(req.request_owner)
        ),
        "responseFromServiceWorker": req.response_from_service_worker,
        "pageSequence": req.page_sequence,
        "capturedAt": req.captured_at,
        "finishedAt": req.finished_at,
    }
