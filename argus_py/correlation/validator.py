"""阶段三：黑白盒关联 — 不变量校验。"""

from __future__ import annotations

from argus_py.correlation.enums import MatchConfidence, MatchStrategy, ResolutionStatus
from argus_py.correlation.models import EndpointEvidence


def validate_endpoint_evidence(evidence: EndpointEvidence) -> None:
    """校验 EndpointEvidence 的不变量，不符合则抛出 ValueError。"""
    if evidence.resolution_status == ResolutionStatus.UNMATCHED:
        if evidence.matched_endpoint_id is not None:
            raise ValueError(
                f"UNMATCHED 条件下 matched_endpoint_id 必须为 None: {evidence.endpoint_evidence_id}"
            )
        if evidence.candidate_count != 0:
            raise ValueError(
                f"UNMATCHED 条件下 candidate_count 必须为 0: {evidence.endpoint_evidence_id}"
            )
        if evidence.match_strategy != MatchStrategy.NONE:
            raise ValueError(
                f"UNMATCHED 条件下 match_strategy 必须为 NONE: {evidence.endpoint_evidence_id}"
            )
        if evidence.confidence != MatchConfidence.UNKNOWN:
            raise ValueError(
                f"UNMATCHED 条件下 confidence 必须为 UNKNOWN: {evidence.endpoint_evidence_id}"
            )

    elif evidence.resolution_status == ResolutionStatus.UNIQUE:
        if evidence.matched_endpoint_id is None:
            raise ValueError(
                f"UNIQUE 条件下 matched_endpoint_id 不能为 None: {evidence.endpoint_evidence_id}"
            )
        if evidence.candidate_count != 1:
            raise ValueError(
                f"UNIQUE 条件下 candidate_count 必须为 1: {evidence.endpoint_evidence_id}"
            )
        if evidence.match_strategy == MatchStrategy.NONE:
            raise ValueError(
                f"UNIQUE 条件下 match_strategy 不能为 NONE: {evidence.endpoint_evidence_id}"
            )

    elif evidence.resolution_status == ResolutionStatus.AMBIGUOUS:
        if evidence.matched_endpoint_id is not None:
            raise ValueError(
                f"AMBIGUOUS 条件下 matched_endpoint_id 必须为 None: {evidence.endpoint_evidence_id}"
            )
        if evidence.candidate_count < 2:
            raise ValueError(
                f"AMBIGUOUS 条件下 candidate_count 必须 >= 2: {evidence.endpoint_evidence_id}"
            )
        if evidence.match_strategy == MatchStrategy.NONE:
            raise ValueError(
                f"AMBIGUOUS 条件下 match_strategy 不能为 NONE: {evidence.endpoint_evidence_id}"
            )


def validate_correlation_run_consistency(
    analysis_id: str | None,
    bound_source_snapshot_id: str | None,
    analysis_projection_version: int | None,
) -> None:
    """校验 CorrelationRun 的三字段一致性。"""
    null_fields = [
        analysis_id is None,
        bound_source_snapshot_id is None,
        analysis_projection_version is None,
    ]
    if not all(null_fields) and not all(not f for f in null_fields):
        raise ValueError(
            "CorrelationRun: analysis_id / bound_source_snapshot_id / "
            "analysis_projection_version 必须同时为 None 或同时非 None。"
        )
