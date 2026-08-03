"""阶段三：不变量校验 — 单元测试。"""

from __future__ import annotations

import pytest
from argus_py.correlation.enums import (
    MatchConfidence,
    MatchStrategy,
    ResolutionStatus,
)
from argus_py.correlation.models import EndpointEvidence
from argus_py.correlation.validator import (
    validate_correlation_run_consistency,
    validate_endpoint_evidence,
)


def _make_evidence(
    endpoint_evidence_id: str = "ev1",
    resolution_status: ResolutionStatus = ResolutionStatus.UNIQUE,
    match_strategy: MatchStrategy = MatchStrategy.EXACT,
    confidence: MatchConfidence = MatchConfidence.HIGH,
    matched_endpoint_id: str | None = "ep1",
    candidate_count: int = 1,
) -> EndpointEvidence:
    return EndpointEvidence(
        endpoint_evidence_id=endpoint_evidence_id,
        correlation_run_id="cr1",
        correlation_attempt_id="ca1",
        request_evidence_id="req1",
        resolution_status=resolution_status,
        match_strategy=match_strategy,
        confidence=confidence,
        matched_endpoint_id=matched_endpoint_id,
        candidate_count=candidate_count,
    )


class TestValidateEndpointEvidence:
    """EndpointEvidence 不变量校验。"""

    # ── UNIQUE ──

    def test_unique_valid(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.UNIQUE,
            match_strategy=MatchStrategy.EXACT,
            confidence=MatchConfidence.HIGH,
            matched_endpoint_id="ep1",
            candidate_count=1,
        )
        validate_endpoint_evidence(ev)  # no raise

    def test_unique_missing_endpoint_id_raises(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.UNIQUE,
            matched_endpoint_id=None,
            candidate_count=1,
        )
        with pytest.raises(ValueError, match="matched_endpoint_id"):
            validate_endpoint_evidence(ev)

    def test_unique_wrong_candidate_count_raises(self) -> None:
        """P1 回归：重叠模板 UNIQUE 的 candidate_count 必须是 1。"""
        ev = _make_evidence(
            resolution_status=ResolutionStatus.UNIQUE,
            candidate_count=3,
        )
        with pytest.raises(ValueError, match="candidate_count 必须为 1"):
            validate_endpoint_evidence(ev)

    def test_unique_with_none_strategy_raises(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.UNIQUE,
            match_strategy=MatchStrategy.NONE,
        )
        with pytest.raises(ValueError, match="match_strategy 不能为 NONE"):
            validate_endpoint_evidence(ev)

    # ── UNMATCHED ──

    def test_unmatched_valid(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.UNMATCHED,
            match_strategy=MatchStrategy.NONE,
            confidence=MatchConfidence.UNKNOWN,
            matched_endpoint_id=None,
            candidate_count=0,
        )
        validate_endpoint_evidence(ev)  # no raise

    def test_unmatched_with_endpoint_id_raises(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.UNMATCHED,
            match_strategy=MatchStrategy.NONE,
            confidence=MatchConfidence.UNKNOWN,
            matched_endpoint_id="ep1",
            candidate_count=0,
        )
        with pytest.raises(ValueError, match="matched_endpoint_id 必须为 None"):
            validate_endpoint_evidence(ev)

    def test_unmatched_wrong_candidate_count_raises(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.UNMATCHED,
            match_strategy=MatchStrategy.NONE,
            confidence=MatchConfidence.UNKNOWN,
            matched_endpoint_id=None,
            candidate_count=1,
        )
        with pytest.raises(ValueError, match="candidate_count 必须为 0"):
            validate_endpoint_evidence(ev)

    def test_unmatched_wrong_strategy_raises(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.UNMATCHED,
            match_strategy=MatchStrategy.EXACT,
            confidence=MatchConfidence.UNKNOWN,
            matched_endpoint_id=None,
            candidate_count=0,
        )
        with pytest.raises(ValueError, match="match_strategy 必须为 NONE"):
            validate_endpoint_evidence(ev)

    def test_unmatched_wrong_confidence_raises(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.UNMATCHED,
            match_strategy=MatchStrategy.NONE,
            confidence=MatchConfidence.HIGH,
            matched_endpoint_id=None,
            candidate_count=0,
        )
        with pytest.raises(ValueError, match="confidence 必须为 UNKNOWN"):
            validate_endpoint_evidence(ev)

    # ── AMBIGUOUS ──

    def test_ambiguous_valid(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.AMBIGUOUS,
            match_strategy=MatchStrategy.TEMPLATE,
            confidence=MatchConfidence.MEDIUM,
            matched_endpoint_id=None,
            candidate_count=3,
        )
        validate_endpoint_evidence(ev)  # no raise

    def test_ambiguous_with_endpoint_id_raises(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.AMBIGUOUS,
            matched_endpoint_id="ep1",
            candidate_count=3,
        )
        with pytest.raises(ValueError, match="matched_endpoint_id 必须为 None"):
            validate_endpoint_evidence(ev)

    def test_ambiguous_candidate_count_too_low_raises(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.AMBIGUOUS,
            matched_endpoint_id=None,
            candidate_count=1,
        )
        with pytest.raises(ValueError, match="candidate_count 必须 >= 2"):
            validate_endpoint_evidence(ev)

    def test_ambiguous_with_none_strategy_raises(self) -> None:
        ev = _make_evidence(
            resolution_status=ResolutionStatus.AMBIGUOUS,
            match_strategy=MatchStrategy.NONE,
            matched_endpoint_id=None,
            candidate_count=3,
        )
        with pytest.raises(ValueError, match="match_strategy 不能为 NONE"):
            validate_endpoint_evidence(ev)


class TestValidateCorrelationRunConsistency:
    """CorrelationRun 三字段一致性。"""

    def test_all_none_valid(self) -> None:
        validate_correlation_run_consistency(None, None, None)  # no raise

    def test_all_some_valid(self) -> None:
        validate_correlation_run_consistency("aid1", "snap1", 1)  # no raise

    def test_partial_null_raises(self) -> None:
        with pytest.raises(ValueError, match="analysis_id"):
            validate_correlation_run_consistency("aid1", None, 1)

    def test_snapshot_null_raises(self) -> None:
        with pytest.raises(ValueError, match="analysis_id"):
            validate_correlation_run_consistency("aid1", "snap1", None)

    def test_version_null_raises(self) -> None:
        with pytest.raises(ValueError, match="analysis_id"):
            validate_correlation_run_consistency(None, "snap1", 1)
