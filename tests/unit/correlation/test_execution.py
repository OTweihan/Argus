"""阶段四：_execution.py 辅助函数 — 单元测试。

覆盖：assess_capture_quality、build_quality_reasons、
resolve_completeness。
"""

from __future__ import annotations

from argus_py.correlation._execution import (
    assess_capture_quality,
    build_quality_reasons,
    resolve_completeness,
)
from argus_py.correlation.enums import PartialReasonCode

# ── assess_capture_quality ──────────────────────────


class TestAssessCaptureQuality:
    def test_normal_data(self) -> None:
        cq = {"truncated": 0, "persistence_failed": 0, "writer_failed_batch_count": 0}
        truncated, failed = assess_capture_quality(cq)
        assert truncated is False
        assert failed is False

    def test_truncated(self) -> None:
        cq = {"truncated": 1, "persistence_failed": 0, "writer_failed_batch_count": 0}
        truncated, failed = assess_capture_quality(cq)
        assert truncated is True
        assert failed is False

    def test_persistence_failed(self) -> None:
        cq = {"truncated": 0, "persistence_failed": 5, "writer_failed_batch_count": 0}
        truncated, failed = assess_capture_quality(cq)
        assert truncated is False
        assert failed is True

    def test_writer_failed_batch_count(self) -> None:
        cq = {"truncated": 0, "persistence_failed": 0, "writer_failed_batch_count": 3}
        truncated, failed = assess_capture_quality(cq)
        assert truncated is False
        assert failed is True

    def test_both_truncated_and_failed(self) -> None:
        cq = {"truncated": 1, "persistence_failed": 2, "writer_failed_batch_count": 1}
        truncated, failed = assess_capture_quality(cq)
        assert truncated is True
        assert failed is True

    def test_none_input(self) -> None:
        truncated, failed = assess_capture_quality(None)
        assert truncated is False
        assert failed is False

    def test_empty_dict(self) -> None:
        truncated, failed = assess_capture_quality({})
        assert truncated is False
        assert failed is False


# ── build_quality_reasons ──────────────────────────


class TestBuildQualityReasons:
    def test_no_reasons(self) -> None:
        reasons, diagnostics = build_quality_reasons("ca1", None, False, False)
        assert reasons == []
        assert diagnostics == []

    def test_capture_truncated(self) -> None:
        cq = {"truncation_reason": "采集量超限"}
        reasons, _ = build_quality_reasons("ca1", cq, True, False)
        assert len(reasons) == 1
        assert reasons[0].reason_code == PartialReasonCode.CAPTURE_TRUNCATED
        assert reasons[0].detail == "采集量超限"

    def test_capture_truncated_no_reason_text(self) -> None:
        reasons, _ = build_quality_reasons("ca1", None, True, False)
        assert len(reasons) == 1
        assert reasons[0].reason_code == PartialReasonCode.CAPTURE_TRUNCATED
        assert reasons[0].detail is not None
        assert "截断" in reasons[0].detail

    def test_persistence_failure(self) -> None:
        cq = {"persistence_failed": 10, "writer_failed_batch_count": 2}
        reasons, _ = build_quality_reasons("ca1", cq, False, True)
        assert len(reasons) == 1
        assert reasons[0].reason_code == PartialReasonCode.REQUEST_PERSISTENCE_FAILED
        assert reasons[0].detail is not None
        assert "10" in reasons[0].detail
        assert "2" in reasons[0].detail

    def test_persistence_failure_no_cq(self) -> None:
        reasons, _ = build_quality_reasons("ca1", None, False, True)
        assert len(reasons) == 1
        assert reasons[0].reason_code == PartialReasonCode.REQUEST_PERSISTENCE_FAILED

    def test_both_reasons(self) -> None:
        cq = {"truncation_reason": "超限", "persistence_failed": 3, "writer_failed_batch_count": 0}
        reasons, _ = build_quality_reasons("ca1", cq, True, True)
        assert len(reasons) == 2
        codes = {r.reason_code for r in reasons}
        assert codes == {
            PartialReasonCode.CAPTURE_TRUNCATED,
            PartialReasonCode.REQUEST_PERSISTENCE_FAILED,
        }


# ── resolve_completeness ──────────────────────────


class TestResolveCompleteness:
    def test_complete(self) -> None:
        assert resolve_completeness(False, False, False).value == "COMPLETE"

    def test_partial_by_reasons(self) -> None:
        assert resolve_completeness(True, False, False).value == "PARTIAL"

    def test_partial_by_truncated(self) -> None:
        assert resolve_completeness(False, True, False).value == "PARTIAL"

    def test_partial_by_failure(self) -> None:
        assert resolve_completeness(False, False, True).value == "PARTIAL"
