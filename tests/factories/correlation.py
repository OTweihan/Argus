"""测试工厂 — 关联相关实体。"""

from __future__ import annotations

from argus_py.correlation.enums import (
    AttemptStatus,
    CorrelationRunStatus,
    EvidenceCompleteness,
    MatchConfidence,
    MatchStrategy,
    ResolutionStatus,
    SourceAlignmentStatus,
)
from argus_py.correlation.models import (
    CorrelationAttempt,
    CorrelationRun,
    EndpointEvidence,
    EndpointEvidenceCandidate,
)


def make_correlation_run(
    correlation_run_id: str = "cr-1",
    project_id: str = "proj-1",
    blackbox_run_id: str = "bb-1",
    desired_source_snapshot_id: str = "abc123",
    correlation_config_digest: str = "d1",
    matcher_version: str = "v1",
    normalization_version: str = "v1",
    analysis_id: str | None = None,
    bound_source_snapshot_id: str | None = None,
    analysis_projection_version: int | None = None,
    status: CorrelationRunStatus = CorrelationRunStatus.WAITING_ANALYSIS,
    active_attempt_id: str | None = None,
    source_alignment_status: SourceAlignmentStatus = SourceAlignmentStatus.UNVERIFIED,
    created_at: str = "2024-01-01T00:00:00",
    **overrides,
) -> CorrelationRun:
    """创建最小化 CorrelationRun，默认值为合法实体。"""
    return CorrelationRun(
        correlation_run_id=correlation_run_id,
        project_id=project_id,
        blackbox_run_id=blackbox_run_id,
        desired_source_snapshot_id=desired_source_snapshot_id,
        correlation_config_digest=correlation_config_digest,
        matcher_version=matcher_version,
        normalization_version=normalization_version,
        analysis_id=analysis_id,
        bound_source_snapshot_id=bound_source_snapshot_id,
        analysis_projection_version=analysis_projection_version,
        status=status,
        active_attempt_id=active_attempt_id,
        source_alignment_status=source_alignment_status,
        created_at=created_at,
        **overrides,
    )


def make_correlation_attempt(
    correlation_attempt_id: str = "ca-1",
    correlation_run_id: str = "cr-1",
    attempt_number: int = 1,
    analysis_id: str = "analysis-1",
    source_snapshot_id: str = "abc123",
    analysis_projection_version: int = 1,
    matcher_version: str = "v1",
    normalization_version: str = "v1",
    correlation_config_digest: str = "d1",
    status: AttemptStatus = AttemptStatus.RUNNING,
    evidence_completeness: EvidenceCompleteness = EvidenceCompleteness.COMPLETE,
    lease_owner: str | None = None,
    started_at: str = "2024-01-01T00:00:00",
    created_at: str = "2024-01-01T00:00:00",
    **overrides,
) -> CorrelationAttempt:
    """创建最小化 CorrelationAttempt。"""
    return CorrelationAttempt(
        correlation_attempt_id=correlation_attempt_id,
        correlation_run_id=correlation_run_id,
        attempt_number=attempt_number,
        analysis_id=analysis_id,
        source_snapshot_id=source_snapshot_id,
        analysis_projection_version=analysis_projection_version,
        matcher_version=matcher_version,
        normalization_version=normalization_version,
        correlation_config_digest=correlation_config_digest,
        status=status,
        evidence_completeness=evidence_completeness,
        lease_owner=lease_owner,
        started_at=started_at,
        created_at=created_at,
        **overrides,
    )


def make_endpoint_evidence(
    endpoint_evidence_id: str = "eev-1",
    correlation_run_id: str = "cr-1",
    correlation_attempt_id: str = "ca-1",
    request_evidence_id: str = "req-1",
    resolution_status: ResolutionStatus = ResolutionStatus.UNIQUE,
    match_strategy: MatchStrategy = MatchStrategy.EXACT,
    confidence: MatchConfidence = MatchConfidence.HIGH,
    matched_endpoint_id: str | None = "ep-1",
    candidate_count: int = 1,
    matcher_version: str = "v1",
    normalization_version: str = "v1",
    created_at: str = "2024-01-01T00:00:00",
    **overrides,
) -> EndpointEvidence:
    """创建最小化 EndpointEvidence。"""
    return EndpointEvidence(
        endpoint_evidence_id=endpoint_evidence_id,
        correlation_run_id=correlation_run_id,
        correlation_attempt_id=correlation_attempt_id,
        request_evidence_id=request_evidence_id,
        resolution_status=resolution_status,
        match_strategy=match_strategy,
        confidence=confidence,
        matched_endpoint_id=matched_endpoint_id,
        candidate_count=candidate_count,
        matcher_version=matcher_version,
        normalization_version=normalization_version,
        created_at=created_at,
        **overrides,
    )


def make_endpoint_evidence_candidate(
    endpoint_evidence_id: str = "eev-1",
    endpoint_id: str = "ep-cand-1",
    candidate_rank: int = 1,
    match_strategy: MatchStrategy = MatchStrategy.TEMPLATE,
    confidence: MatchConfidence = MatchConfidence.MEDIUM,
    selected: bool = False,
    **overrides,
) -> EndpointEvidenceCandidate:
    """创建最小化 EndpointEvidenceCandidate。"""
    return EndpointEvidenceCandidate(
        endpoint_evidence_id=endpoint_evidence_id,
        endpoint_id=endpoint_id,
        candidate_rank=candidate_rank,
        match_strategy=match_strategy,
        confidence=confidence,
        selected=selected,
        **overrides,
    )
