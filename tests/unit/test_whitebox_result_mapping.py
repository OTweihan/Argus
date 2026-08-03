"""阶段四：白盒结果映射纯函数 — 单元测试。

覆盖：_map_severity、_map_finding_type、_resolve_source_location、
_compute_fingerprint、_map_findings、_build_diag_summary、
_build_projection_data。
"""

from __future__ import annotations

import pytest
from argus_py.core.enums import FindingSeverity, FindingType
from argus_py.whitebox.models import (
    AnalyzerDiagnostics,
    CallGraph,
    CallGraphNode,
    SourceLocationData,
    WhiteboxFinding,
    WhiteboxResult,
)
from argus_py.whitebox.runner import (
    _build_diag_summary,
    _build_projection_data,
    _compute_fingerprint,
    _map_finding_type,
    _map_findings,
    _map_severity,
    _resolve_source_location,
)

# ── _map_severity ─────────────────────────────────


class TestMapSeverity:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("CRITICAL", FindingSeverity.CRITICAL),
            ("HIGH", FindingSeverity.HIGH),
            ("MEDIUM", FindingSeverity.MEDIUM),
            ("LOW", FindingSeverity.LOW),
            ("INFO", FindingSeverity.INFO),
            ("critical", FindingSeverity.CRITICAL),
        ],
    )
    def test_known_values(self, raw: str, expected: FindingSeverity) -> None:
        assert _map_severity(raw) == expected

    def test_unknown_falls_back_to_info(self) -> None:
        assert _map_severity("UNKNOWN_LEVEL") == FindingSeverity.INFO


# ── _map_finding_type ─────────────────────────────


class TestMapFindingType:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("SECURITY", FindingType.SECURITY),
            ("BUG", FindingType.FUNCTIONAL),
            ("PERFORMANCE", FindingType.PERFORMANCE),
            ("STYLE", FindingType.STYLE),
            ("CODE_SMELL", FindingType.CODE_QUALITY),
            ("UNKNOWN", FindingType.UNKNOWN),
        ],
    )
    def test_known_values(self, raw: str, expected: FindingType) -> None:
        assert _map_finding_type(raw) == expected

    def test_none_returns_unknown(self) -> None:
        assert _map_finding_type(None) == FindingType.UNKNOWN

    def test_empty_string_returns_unknown(self) -> None:
        assert _map_finding_type("") == FindingType.UNKNOWN

    def test_random_string_returns_unknown(self) -> None:
        assert _map_finding_type("RANDOM") == FindingType.UNKNOWN


# ── _resolve_source_location ─────────────────────


class TestResolveSourceLocation:
    def test_prefers_source_location(self) -> None:
        wf = WhiteboxFinding(
            rule_id="R1",
            severity="MEDIUM",
            title="T",
            description="D",
            file_path="old.java",
            line_number=10,
            source_location=SourceLocationData(
                file_path="new.java",
                start_line=5,
            ),
        )
        result = _resolve_source_location(wf)
        assert result is not None
        assert result.file_path == "new.java"
        assert result.start_line == 5

    def test_fallback_to_file_path(self) -> None:
        wf = WhiteboxFinding(
            rule_id="R1",
            severity="MEDIUM",
            title="T",
            description="D",
            file_path="fallback.java",
            line_number=10,
        )
        result = _resolve_source_location(wf)
        assert result is not None
        assert result.file_path == "fallback.java"
        assert result.start_line == 10

    def test_rejects_zero_start_line(self) -> None:
        wf = WhiteboxFinding(
            rule_id="R1",
            severity="MEDIUM",
            title="T",
            description="D",
            file_path="bad.java",
            line_number=0,
        )
        result = _resolve_source_location(wf)
        assert result is None

    def test_no_location_no_file_path_returns_none(self) -> None:
        wf = WhiteboxFinding(
            rule_id="R1",
            severity="MEDIUM",
            title="T",
            description="D",
            file_path="",
            line_number=0,
        )
        result = _resolve_source_location(wf)
        assert result is None


# ── _compute_fingerprint ─────────────────────────


class TestComputeFingerprint:
    def test_deterministic(self) -> None:
        fp1 = _compute_fingerprint("R1", "file.java", 10, "Title")
        fp2 = _compute_fingerprint("R1", "file.java", 10, "Title")
        assert fp1 == fp2
        assert len(fp1) == 64

    def test_different_inputs_produce_different(self) -> None:
        fp1 = _compute_fingerprint("R1", "file.java", 10, "Title")
        fp2 = _compute_fingerprint("R2", "file.java", 10, "Title")
        assert fp1 != fp2

    def test_whitespace_in_title_normalized(self) -> None:
        fp1 = _compute_fingerprint("R1", "f.java", 1, "  Title  ")
        fp2 = _compute_fingerprint("R1", "f.java", 1, "Title")
        assert fp1 == fp2


# ── _map_findings ────────────────────────────────


class TestMapFindings:
    def test_dedup_same_fingerprint(self) -> None:
        wfs = [
            WhiteboxFinding(
                rule_id="R1",
                severity="MEDIUM",
                title="Bug",
                description="desc",
                file_path="a.java",
                line_number=10,
                source_location=SourceLocationData(file_path="a.java", start_line=10),
            ),
            WhiteboxFinding(
                rule_id="R1",
                severity="MEDIUM",
                title="Bug",
                description="desc",
                file_path="a.java",
                line_number=10,
                source_location=SourceLocationData(file_path="a.java", start_line=10),
            ),
        ]
        result = _map_findings(wfs)
        assert len(result) == 1

    def test_analysis_id_propagated(self) -> None:
        wfs = [
            WhiteboxFinding(
                rule_id="R1",
                severity="MEDIUM",
                title="Bug",
                description="desc",
                file_path="a.java",
                line_number=10,
                source_location=SourceLocationData(file_path="a.java", start_line=10),
            ),
        ]
        result = _map_findings(wfs, analysis_id="aid-123")
        assert result[0].analysis_id == "aid-123"

    def test_snippet_propagated(self) -> None:
        wfs = [
            WhiteboxFinding(
                rule_id="R1",
                severity="MEDIUM",
                title="Bug",
                description="desc",
                file_path="a.java",
                line_number=10,
                snippet="catch (Exception e) {}",
                source_location=SourceLocationData(file_path="a.java", start_line=10),
            ),
        ]
        result = _map_findings(wfs)
        assert result[0].snippet == "catch (Exception e) {}"

    def test_no_source_location_still_included(self) -> None:
        """无有效 source_location 的 finding 仍应出现在结果中（location 回退到
        file_path），但不计算 fingerprint，也不会去重。"""
        wfs = [
            WhiteboxFinding(
                rule_id="R1",
                severity="MEDIUM",
                title="Bug",
                description="desc",
                file_path="a.java",
                line_number=0,
            ),
        ]
        result = _map_findings(wfs)
        assert len(result) == 1
        assert result[0].location == "a.java"


# ── _build_diag_summary ──────────────────────────


class TestBuildDiagSummary:
    def test_complete_diag(self) -> None:
        d = AnalyzerDiagnostics(
            total_source_files=100,
            parsed_file_count=95,
            failed_file_count=5,
            total_calls=50,
            resolved_high=40,
            resolved_medium=5,
            resolved_low=3,
            unresolved=2,
            classpath_available=True,
            jar_count=30,
        )
        summary = _build_diag_summary(d)
        assert "95/100" in summary
        assert "50" in summary  # total_calls
        assert "30" in summary  # jar_count

    def test_no_classpath(self) -> None:
        d = AnalyzerDiagnostics(
            total_source_files=100,
            parsed_file_count=95,
            total_calls=50,
            resolved_high=10,
            resolved_medium=5,
            resolved_low=15,
            unresolved=20,
            classpath_available=False,
            classpath_source="none",
        )
        summary = _build_diag_summary(d)
        assert "无 classpath" in summary or "降级" in summary

    def test_none_diagnostics(self) -> None:
        assert _build_diag_summary(None) == ""


# ── _build_projection_data ───────────────────────


class TestBuildProjectionData:
    def test_empty_result(self) -> None:
        result = WhiteboxResult()
        data = _build_projection_data(result, analysis_id="aid-1")
        assert data["call_nodes"] == []
        assert data["call_edges"] == []
        assert data["execution_flows"] == []
        assert data["endpoints"] == []
        assert data["clusters"] == []
        assert data["diagnostics"] is None

    def test_call_edges_skip_empty_to(self) -> None:
        result = WhiteboxResult(
            call_graph=CallGraph(
                nodes={
                    "com.example.A#method": CallGraphNode(
                        class_name="com.example.A",
                        method_name="method",
                        method_signature="void method()",
                        callee_details=[],
                    ),
                }
            ),
        )
        data = _build_projection_data(result, analysis_id="aid-1")
        assert len(data["call_nodes"]) == 1
        assert data["call_edges"] == []
