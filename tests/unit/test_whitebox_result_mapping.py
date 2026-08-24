"""阶段四：白盒结果映射纯函数 — 单元测试。

覆盖：_map_severity、_map_finding_type、_compute_fingerprint、
_map_findings、_build_diag_summary、_build_projection_data。
"""

from __future__ import annotations

import pytest
from argus_py.core.enums import FindingSeverity, FindingType
from argus_py.whitebox.models import (
    AnalyzerDiagnostics,
    CallGraph,
    CallGraphNode,
    ExecutionFlow,
    FlowStep,
    WhiteboxFinding,
    WhiteboxResult,
)
from argus_py.whitebox.projection import (
    build_projection_data,
    compute_fingerprint,
    evaluate_completeness,
    map_finding_type,
    map_findings,
    map_severity,
)
from argus_py.whitebox.runner import _build_diag_summary

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
        assert map_severity(raw) == expected

    def test_unknown_falls_back_to_info(self) -> None:
        assert map_severity("UNKNOWN_LEVEL") == FindingSeverity.INFO


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
        assert map_finding_type(raw) == expected

    def test_none_returns_unknown(self) -> None:
        assert map_finding_type(None) == FindingType.UNKNOWN

    def test_empty_string_returns_unknown(self) -> None:
        assert map_finding_type("") == FindingType.UNKNOWN

    def test_random_string_returns_unknown(self) -> None:
        assert map_finding_type("RANDOM") == FindingType.UNKNOWN


# ── _compute_fingerprint ─────────────────────────


class TestComputeFingerprint:
    def test_deterministic(self) -> None:
        fp1 = compute_fingerprint("R1", "file.java", 10, "Title")
        fp2 = compute_fingerprint("R1", "file.java", 10, "Title")
        assert fp1 == fp2
        assert len(fp1) == 64

    def test_different_inputs_produce_different(self) -> None:
        fp1 = compute_fingerprint("R1", "file.java", 10, "Title")
        fp2 = compute_fingerprint("R2", "file.java", 10, "Title")
        assert fp1 != fp2

    def test_whitespace_in_title_normalized(self) -> None:
        fp1 = compute_fingerprint("R1", "f.java", 1, "  Title  ")
        fp2 = compute_fingerprint("R1", "f.java", 1, "Title")
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
            ),
            WhiteboxFinding(
                rule_id="R1",
                severity="MEDIUM",
                title="Bug",
                description="desc",
                file_path="a.java",
                line_number=10,
            ),
        ]
        result = map_findings(wfs)
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
            ),
        ]
        result = map_findings(wfs, analysis_id="aid-123")
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
            ),
        ]
        result = map_findings(wfs)
        assert result[0].snippet == "catch (Exception e) {}"

    def test_invalid_location_still_included(self) -> None:
        """line_number 无效（<1）的 finding 仍应出现在结果中（location 回退到
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
        result = map_findings(wfs)
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


# ── _evaluate_completeness ───────────────────────


class TestEvaluateCompleteness:
    def test_none_diagnostics_not_evaluated(self) -> None:
        status, issues = evaluate_completeness(None)
        assert status == "NOT_EVALUATED"
        assert issues == []

    def test_complete(self) -> None:
        d = AnalyzerDiagnostics(
            total_source_files=10,
            parsed_file_count=10,
            failed_file_count=0,
            total_calls=5,
            resolved_high=5,
            resolved_medium=0,
            unresolved=0,
            classpath_available=True,
        )
        status, issues = evaluate_completeness(d)
        assert status == "COMPLETE"
        assert issues == []

    def test_no_eligible_source_unavailable(self) -> None:
        d = AnalyzerDiagnostics(total_source_files=0)
        status, issues = evaluate_completeness(d)
        assert status == "UNAVAILABLE"
        assert issues[0]["code"] == "NO_ELIGIBLE_SOURCE_FILES"

    def test_parse_partial_failure_degrades(self) -> None:
        d = AnalyzerDiagnostics(
            total_source_files=10,
            parsed_file_count=8,
            failed_file_count=2,
            classpath_available=True,
        )
        status, issues = evaluate_completeness(d)
        assert status == "DEGRADED"
        codes = [i["code"] for i in issues]
        assert "MODULE_PARSE_PARTIAL_FAILURE" in codes

    def test_classpath_unavailable_degrades(self) -> None:
        d = AnalyzerDiagnostics(
            total_source_files=10,
            parsed_file_count=10,
            failed_file_count=0,
            total_calls=5,
            resolved_high=5,
            classpath_available=False,
        )
        status, issues = evaluate_completeness(d)
        assert status == "DEGRADED"
        codes = [i["code"] for i in issues]
        assert "CLASSPATH_UNAVAILABLE" in codes

    def test_call_resolution_low_degrades(self) -> None:
        d = AnalyzerDiagnostics(
            total_source_files=10,
            parsed_file_count=10,
            failed_file_count=0,
            total_calls=10,
            resolved_high=3,
            resolved_medium=2,
            resolved_low=4,
            unresolved=1,
            classpath_available=True,
            jar_count=5,
        )
        status, issues = evaluate_completeness(d)
        assert status == "DEGRADED"
        codes = [i["code"] for i in issues]
        assert "CALL_RESOLUTION_LOW" in codes

    def test_pass_failures_degrade_with_no_other_issue(self) -> None:
        """O-11：仅可选 pass 失败（其余诊断正常）→ 显式降级而非静默 COMPLETE。"""
        d = AnalyzerDiagnostics(
            total_source_files=10,
            parsed_file_count=10,
            failed_file_count=0,
            total_calls=5,
            resolved_high=5,
            classpath_available=True,
            pass_failures=["flows: tracer bug", "clusters: npe"],
        )
        status, issues = evaluate_completeness(d)
        assert status == "DEGRADED"
        codes = [i["code"] for i in issues]
        assert "ANALYSIS_PASS_FAILED" in codes
        issue = next(i for i in issues if i["code"] == "ANALYSIS_PASS_FAILED")
        assert "flows: tracer bug" in issue["message"]
        assert issue["affectedCount"] == 2
        assert issue["totalCount"] == 2


# ── _serialize_whitebox_result ───────────────────


class TestSerializeWhiteboxResult:
    def test_serializes_completeness_and_quality_issues(self) -> None:
        from argus_py.whitebox.projection import serialize_whitebox_result

        d = AnalyzerDiagnostics(
            total_source_files=10,
            parsed_file_count=8,
            failed_file_count=2,
            classpath_available=False,
        )
        result = WhiteboxResult(diagnostics=d)
        data = serialize_whitebox_result(result, 0, 0, "all")
        assert data["completeness"] == "DEGRADED"
        codes = [i["code"] for i in data["qualityIssues"]]
        assert "MODULE_PARSE_PARTIAL_FAILURE" in codes
        assert "CLASSPATH_UNAVAILABLE" in codes

    def test_serializes_not_evaluated_without_diagnostics(self) -> None:
        from argus_py.whitebox.projection import serialize_whitebox_result

        data = serialize_whitebox_result(WhiteboxResult(), 0, 0, "all")
        assert data["completeness"] == "NOT_EVALUATED"
        assert data["qualityIssues"] == []


# ── _build_projection_data ───────────────────────


class TestBuildProjectionData:
    def test_empty_result(self) -> None:
        result = WhiteboxResult()
        data = build_projection_data(result, analysis_id="aid-1")
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
        data = build_projection_data(result, analysis_id="aid-1")
        assert len(data["call_nodes"]) == 1
        assert data["call_edges"] == []

    def test_call_node_source_location_normalized_to_none(self) -> None:
        """CallNode 的 source_* 投影统一为 None（与端点列一致）。

        Java CallGraphNode 暂不返回源码位置，空串 "" 会与端点列的
        NULL 语义不一致；此处锁定为 None，避免后续误判为已有源码位置。
        """
        result = WhiteboxResult(
            call_graph=CallGraph(
                nodes={
                    "com.example.A#method": CallGraphNode(
                        class_name="com.example.A",
                        method_name="method",
                        method_signature="void method()",
                    ),
                }
            ),
        )
        data = build_projection_data(result, analysis_id="aid-1")
        node = data["call_nodes"][0]
        assert node["source_file"] is None
        assert node["source_start_line"] is None
        assert node["source_start_column"] is None
        assert node["source_end_line"] is None
        assert node["source_end_column"] is None

    def test_execution_flows_dedup_same_entry_point(self) -> None:
        """同一分析内按 entry_point 去重，避免唯一约束冲突。

        回归：Java ExecutionFlowTracer 按端点生成执行流，多个端点共享同一
        controller 方法时会产出 entry_point 相同的多条流（步骤一致），而
        analysis_execution_flows 唯一约束为 (analysis_id, execution_flow_fingerprint)，
        重复指纹会导致投影事务整体回滚（sqlite3.IntegrityError）。
        """
        flow_steps = [
            FlowStep(depth=0, method_key="com.example.A#method"),
            FlowStep(depth=1, method_key="com.example.B#helper"),
        ]
        result = WhiteboxResult(
            execution_flows=[
                ExecutionFlow(
                    entry_point="com.example.A#method",
                    steps=flow_steps,
                    call_depth=1,
                ),
                ExecutionFlow(
                    entry_point="com.example.A#method",
                    steps=flow_steps,
                    call_depth=1,
                ),
                ExecutionFlow(
                    entry_point="com.example.C#other",
                    steps=[FlowStep(depth=0, method_key="com.example.C#other")],
                    call_depth=0,
                ),
            ],
        )
        data = build_projection_data(result, analysis_id="aid-1")
        assert len(data["execution_flows"]) == 2
        fingerprints = [f["execution_flow_fingerprint"] for f in data["execution_flows"]]
        assert len(fingerprints) == len(set(fingerprints))
        assert data["execution_flows"][0]["entry_point"] == "com.example.A#method"
        assert data["execution_flows"][1]["entry_point"] == "com.example.C#other"
        # 重复 entry_point 的 steps 不重复写入
        assert len(data["flow_steps"]) == 3
