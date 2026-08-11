"""分析执行领域 — 单元测试。

覆盖 ``argus_py.analysis.enums``（状态机/枚举）、``argus_py.analysis.models``（dataclass）
和 ``argus_py.api.schemas.analysis``（Pydantic 响应模型）的核心行为。

注：本文件刻意用 camelCase 别名构造 Pydantic 响应模型，以验证 ``ApiModel`` 的
``populate_by_name=True`` 别名输入契约（外部客户端按 OpenAPI 的 camelCase 调用）。
mypy 的 pydantic 插件只识别 snake_case 字段名、不识别 alias，会把这些合法调用误报为
call-arg，故在文件级关闭该错误码。
"""

# mypy: disable-error-code="call-arg"

from __future__ import annotations

import pytest
from argus_py.analysis.enums import (
    AnalysisConfidence,
    AnalysisRunStatus,
    AnalysisScope,
    CompletenessStatus,
    QualityIssueCode,
    QualityIssueLevel,
    RuleCategory,
    get_quality_issue_defaults,
    is_valid_transition,
)
from argus_py.analysis.models import (
    AnalysisMetrics,
    AnalysisRun,
    QualityIssue,
    SourceLocation,
)
from argus_py.api.schemas.analysis import (
    AnalysisRunListResponse,
    AnalysisRunSummaryResponse,
    CallEdgeResponse,
    CallGraphPageResponse,
    CallNodePageResponse,
    CallNodeResponse,
    CompletenessMetricsResponse,
    CompletenessResponse,
    DiagnosticsResponse,
    EndpointPageResponse,
    EndpointResponse,
    ExecutionFlowPageResponse,
    ExecutionFlowResponse,
    ExecutionFlowStepResponse,
    QualityIssueResponse,
    SourceLocationResponse,
)

# ═══════════════════════════════════════════════════════════════════════════════
# AnalysisRunStatus — 生命周期状态
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalysisRunStatus:
    """AnalysisRunStatus 枚举及其状态机。"""

    @pytest.mark.parametrize(
        ("status", "terminal"),
        [
            (AnalysisRunStatus.QUEUED, False),
            (AnalysisRunStatus.SUBMITTING, False),
            (AnalysisRunStatus.RUNNING, False),
            (AnalysisRunStatus.SUCCEEDED, True),
            (AnalysisRunStatus.FAILED, True),
            (AnalysisRunStatus.TIMED_OUT, True),
            (AnalysisRunStatus.CANCELLED, True),
            (AnalysisRunStatus.STOPPED_WAITING, True),
        ],
    )
    def test_is_terminal(self, status: AnalysisRunStatus, terminal: bool) -> None:
        """终态标志仅 SUCCEEDED/FAILED/TIMED_OUT/CANCELLED/STOPPED_WAITING 为 True。"""
        assert status.is_terminal is terminal

    def test_str_value(self) -> None:
        """str,Enum 的 value 比较：枚举成员 == 字符串值。"""
        assert AnalysisRunStatus.RUNNING == "RUNNING"
        assert AnalysisRunStatus.RUNNING.value == "RUNNING"


class TestStateTransitions:
    """is_valid_transition 合法迁移校验。"""

    QUEUED = AnalysisRunStatus.QUEUED
    SUBMITTING = AnalysisRunStatus.SUBMITTING
    RUNNING = AnalysisRunStatus.RUNNING
    SUCCEEDED = AnalysisRunStatus.SUCCEEDED
    FAILED = AnalysisRunStatus.FAILED
    TIMED_OUT = AnalysisRunStatus.TIMED_OUT
    CANCELLED = AnalysisRunStatus.CANCELLED
    STOPPED_WAITING = AnalysisRunStatus.STOPPED_WAITING

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (QUEUED, SUBMITTING),
            (QUEUED, CANCELLED),
            (SUBMITTING, RUNNING),
            (SUBMITTING, FAILED),
            (SUBMITTING, CANCELLED),
            (RUNNING, SUCCEEDED),
            (RUNNING, FAILED),
            (RUNNING, TIMED_OUT),
            (RUNNING, CANCELLED),
            (RUNNING, STOPPED_WAITING),
        ],
    )
    def test_valid_transitions(self, current: AnalysisRunStatus, target: AnalysisRunStatus) -> None:
        """合法状态迁移应被接受。"""
        assert is_valid_transition(current, target) is True

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            # 终态不允许任何迁移
            (SUCCEEDED, RUNNING),
            (SUCCEEDED, QUEUED),
            (FAILED, QUEUED),
            (FAILED, RUNNING),
            (TIMED_OUT, RUNNING),
            (CANCELLED, QUEUED),
            (STOPPED_WAITING, SUCCEEDED),
            # 非法反向
            (RUNNING, QUEUED),
            (SUBMITTING, QUEUED),
        ],
    )
    def test_invalid_transitions(
        self, current: AnalysisRunStatus, target: AnalysisRunStatus
    ) -> None:
        """非法状态迁移（终态迁移/反向迁移）必须被拒绝。"""
        assert is_valid_transition(current, target) is False

    def test_all_terminals_are_invalid_sources(self) -> None:
        """所有终态都不应允许任何迁移。"""
        for terminal in (
            self.SUCCEEDED,
            self.FAILED,
            self.TIMED_OUT,
            self.CANCELLED,
            self.STOPPED_WAITING,
        ):
            for other in AnalysisRunStatus:
                assert not is_valid_transition(terminal, other), (
                    f"{terminal.value} 不应迁移到 {other.value}"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# CompletenessStatus
# ═══════════════════════════════════════════════════════════════════════════════


def test_completeness_status_values() -> None:
    """CompletenessStatus 包含预期成员。"""
    assert CompletenessStatus.NOT_EVALUATED == "NOT_EVALUATED"
    assert CompletenessStatus.COMPLETE == "COMPLETE"
    assert CompletenessStatus.DEGRADED == "DEGRADED"
    assert CompletenessStatus.UNAVAILABLE == "UNAVAILABLE"


# ═══════════════════════════════════════════════════════════════════════════════
# RuleCategory / AnalysisConfidence
# ═══════════════════════════════════════════════════════════════════════════════


def test_rule_category_has_unknown() -> None:
    """RuleCategory 必须包含 UNKNOWN 枚举（Java 不返回 null）。"""
    assert RuleCategory.UNKNOWN == "UNKNOWN"


def test_analysis_confidence_has_unknown() -> None:
    """AnalysisConfidence 必须包含 UNKNOWN 枚举。"""
    assert AnalysisConfidence.UNKNOWN == "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════════════════
# AnalysisScope
# ═══════════════════════════════════════════════════════════════════════════════


def test_analysis_scope_values() -> None:
    """首期只开放 ALL 和 MODULES。"""
    assert AnalysisScope.ALL == "ALL"
    assert AnalysisScope.MODULES == "MODULES"


# ═══════════════════════════════════════════════════════════════════════════════
# QualityIssueCode — 中央映射表
# ═══════════════════════════════════════════════════════════════════════════════


class TestQualityIssueDefaults:
    """get_quality_issue_defaults 覆盖全部已知代码。"""

    def test_no_eligible_source_files_maps_to_unavailable(self) -> None:
        _level, impact = get_quality_issue_defaults(QualityIssueCode.NO_ELIGIBLE_SOURCE_FILES)
        assert impact is CompletenessStatus.UNAVAILABLE

    def test_module_parse_partial_failure_maps_to_degraded(self) -> None:
        _level, impact = get_quality_issue_defaults(QualityIssueCode.MODULE_PARSE_PARTIAL_FAILURE)
        assert impact is CompletenessStatus.DEGRADED

    def test_classpath_degraded_maps_to_degraded(self) -> None:
        _level, impact = get_quality_issue_defaults(QualityIssueCode.CLASSPATH_DEGRADED)
        assert impact is CompletenessStatus.DEGRADED

    def test_classpath_unavailable_has_no_fixed_impact(self) -> None:
        """CLASSPATH_UNAVAILABLE 的影响取决于上下文，不应预设为单一完整性状态。"""
        _level, impact = get_quality_issue_defaults(QualityIssueCode.CLASSPATH_UNAVAILABLE)
        assert impact is None

    def test_call_resolution_low_maps_to_degraded(self) -> None:
        _level, impact = get_quality_issue_defaults(QualityIssueCode.CALL_RESOLUTION_LOW)
        assert impact is CompletenessStatus.DEGRADED

    def test_analysis_pass_failed_maps_to_degraded(self) -> None:
        """O-11：可选 AnalysisPass 失败 → 显式降级。"""
        level, impact = get_quality_issue_defaults(QualityIssueCode.ANALYSIS_PASS_FAILED)
        assert level is QualityIssueLevel.WARNING
        assert impact is CompletenessStatus.DEGRADED

    def test_zero_findings_does_not_affect_completeness(self) -> None:
        """零发现项是合法结果，不应当影响完整性判定。"""
        _level, impact = get_quality_issue_defaults(QualityIssueCode.ZERO_FINDINGS)
        assert impact is None

    def test_schema_version_mismatch_no_impact(self) -> None:
        """SCHEMA_VERSION_MISMATCH 应阻止执行，不作为 QualityIssue 影响完整性。"""
        _level, impact = get_quality_issue_defaults(QualityIssueCode.SCHEMA_VERSION_MISMATCH)
        assert impact is None

    def test_all_codes_return_valid_level(self) -> None:
        """所有 QualityIssueCode 都应返回有效的 QualityIssueLevel。"""
        for code in QualityIssueCode:
            level, _impact = get_quality_issue_defaults(code)
            assert level in QualityIssueLevel


# ═══════════════════════════════════════════════════════════════════════════════
# SourceLocation
# ═══════════════════════════════════════════════════════════════════════════════


class TestSourceLocation:
    """SourceLocation.to_display() 格式化。"""

    def test_full_location(self) -> None:
        sl = SourceLocation(
            file_path="src/Foo.java",
            start_line=42,
            start_column=5,
            end_line=45,
            end_column=10,
        )
        assert sl.to_display() == "src/Foo.java:42:5-45:10"

    def test_line_only(self) -> None:
        """只有行号时列出 file:line。"""
        sl = SourceLocation(file_path="src/Foo.java", start_line=42)
        assert sl.to_display() == "src/Foo.java:42"

    def test_line_and_column(self) -> None:
        sl = SourceLocation(file_path="src/Foo.java", start_line=42, start_column=3)
        assert sl.to_display() == "src/Foo.java:42:3"

    def test_single_line_range(self) -> None:
        """end_line 与 start_line 相同时不显示范围。"""
        sl = SourceLocation(
            file_path="src/Foo.java",
            start_line=42,
            end_line=42,
            end_column=20,
        )
        assert sl.to_display() == "src/Foo.java:42"

    def test_empty_file_path(self) -> None:
        """缺少文件路径时返回占位。"""
        sl = SourceLocation(file_path="", start_line=10)
        assert sl.to_display() == "(unknown)"

    def test_start_line_zero(self) -> None:
        """start_line < 1 时仅返回文件名，不伪造 line:0。"""
        sl = SourceLocation(file_path="src/Foo.java", start_line=0)
        assert sl.to_display() == "src/Foo.java"


# ═══════════════════════════════════════════════════════════════════════════════
# QualityIssue
# ═══════════════════════════════════════════════════════════════════════════════


class TestQualityIssue:
    """QualityIssue 序列化/反序列化往返。"""

    def test_to_dict_basic(self) -> None:
        qi = QualityIssue(code="CLASSPATH_DEGRADED", level="WARNING", message="classpath degraded")
        d = qi.to_dict()
        assert d["code"] == "CLASSPATH_DEGRADED"
        assert d["message"] == "classpath degraded"
        assert d["affectedCount"] is None

    def test_to_dict_with_counts(self) -> None:
        qi = QualityIssue(
            code="MODULE_PARSE_PARTIAL_FAILURE",
            level="WARNING",
            message="partial failure",
            affected_count=10,
            total_count=50,
        )
        d = qi.to_dict()
        assert d["affectedCount"] == 10
        assert d["totalCount"] == 50

    def test_from_dict_roundtrip(self) -> None:
        original = QualityIssue(
            code="CALL_RESOLUTION_LOW",
            level="WARNING",
            message="low resolution",
            affected_count=20,
            total_count=100,
        )
        restored = QualityIssue.from_dict(original.to_dict())
        assert restored.code == original.code
        assert restored.level == original.level
        assert restored.message == original.message
        assert restored.affected_count == original.affected_count
        assert restored.total_count == original.total_count


# ═══════════════════════════════════════════════════════════════════════════════
# AnalysisRun
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalysisRun:
    """AnalysisRun 领域模型。"""

    def test_defaults(self) -> None:
        run = AnalysisRun(analysis_id="ar-1", task_id="t-1", source_snapshot_id="ss-1")
        assert run.run_status == "QUEUED"
        assert run.completeness_status == "NOT_EVALUATED"
        assert run.result_schema_version == 1
        assert run.quality_policy_version == 1
        assert run.quality_issues == []
        assert not run.is_terminal

    def test_is_terminal_for_succeeded(self) -> None:
        run = AnalysisRun(
            analysis_id="ar-1",
            task_id="t-1",
            source_snapshot_id="ss-1",
            run_status="SUCCEEDED",
        )
        assert run.is_terminal

    def test_is_terminal_for_failed(self) -> None:
        run = AnalysisRun(
            analysis_id="ar-1",
            task_id="t-1",
            source_snapshot_id="ss-1",
            run_status="FAILED",
        )
        assert run.is_terminal

    def test_run_status_enum(self) -> None:
        run = AnalysisRun(
            analysis_id="ar-1",
            task_id="t-1",
            source_snapshot_id="ss-1",
            run_status="RUNNING",
        )
        assert run.run_status_enum is AnalysisRunStatus.RUNNING

    def test_completeness_status_enum(self) -> None:
        run = AnalysisRun(
            analysis_id="ar-1",
            task_id="t-1",
            source_snapshot_id="ss-1",
            run_status="SUCCEEDED",
            completeness_status="DEGRADED",
        )
        assert run.completeness_status_enum is CompletenessStatus.DEGRADED

    def test_stopped_waiting_is_terminal(self) -> None:
        """STOPPED_WAITING 是终态，不可被远端异步成功静默覆盖。"""
        run = AnalysisRun(
            analysis_id="ar-1",
            task_id="t-1",
            source_snapshot_id="ss-1",
            run_status="STOPPED_WAITING",
        )
        assert run.is_terminal
        assert not is_valid_transition(
            AnalysisRunStatus.STOPPED_WAITING, AnalysisRunStatus.SUCCEEDED
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AnalysisMetrics
# ═══════════════════════════════════════════════════════════════════════════════


def test_analysis_metrics_defaults() -> None:
    m = AnalysisMetrics()
    assert m.eligible_source_files == 0
    assert m.resolved_calls == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic 响应模型 — 基础构造
# ═══════════════════════════════════════════════════════════════════════════════


class TestSourceLocationResponse:
    """SourceLocationResponse alias 别名。"""

    def test_from_python_names(self) -> None:
        """支持 Python 侧 snake_case 输入并正确序列化 camelCase。"""
        sl = SourceLocationResponse(
            file_path="src/Foo.java",
            start_line=10,
            start_column=5,
            end_line=12,
            end_column=20,
        )
        data = sl.model_dump(by_alias=True)
        assert data["filePath"] == "src/Foo.java"
        assert data["startLine"] == 10
        assert data["startColumn"] == 5
        assert data["endLine"] == 12
        assert data["endColumn"] == 20

    def test_from_alias_names(self) -> None:
        """支持 camelCase 输入构造。"""
        sl = SourceLocationResponse.model_validate(
            {
                "filePath": "src/Bar.java",
                "startLine": 3,
            }
        )
        assert sl.file_path == "src/Bar.java"
        assert sl.start_line == 3
        assert sl.start_column is None

    def test_optional_fields_default_to_none(self) -> None:
        sl = SourceLocationResponse(file_path="src/Foo.java", start_line=1)
        assert sl.end_line is None
        assert sl.end_column is None


class TestQualityIssueResponse:
    """QualityIssueResponse 模型。"""

    def test_minimal(self) -> None:
        qi = QualityIssueResponse(
            code=QualityIssueCode.CLASSPATH_DEGRADED,
            level=QualityIssueLevel.WARNING,
            message="classpath degraded",
        )
        data = qi.model_dump(by_alias=True)
        assert data["code"] == "CLASSPATH_DEGRADED"
        assert data["level"] == "WARNING"


class TestCompletenessResponse:
    """CompletenessResponse 包装完整性结论。"""

    def test_complete(self) -> None:
        metrics = CompletenessMetricsResponse(
            eligible_source_files=100,
            parsed_source_files=95,
            total_calls=500,
            resolved_calls=420,
        )
        cr = CompletenessResponse(
            status=CompletenessStatus.DEGRADED,
            issues=[],
            metrics=metrics,
        )
        data = cr.model_dump(by_alias=True)
        assert data["status"] == "DEGRADED"
        assert data["metrics"]["eligibleSourceFiles"] == 100


# ═══════════════════════════════════════════════════════════════════════════════
# AnalysisRunSummaryResponse — 摘要构造
# ═══════════════════════════════════════════════════════════════════════════════

_FAKE_COMPLETENESS = CompletenessResponse(
    status=CompletenessStatus.NOT_EVALUATED,
    issues=[],
    metrics=CompletenessMetricsResponse(
        eligible_source_files=0,
        parsed_source_files=0,
        total_calls=0,
        resolved_calls=0,
    ),
)


def test_analysis_run_summary_response() -> None:
    summary = AnalysisRunSummaryResponse(
        analysisId="ar-1",
        taskId="t-1",
        sourceSnapshotId="ss-1",
        runStatus=AnalysisRunStatus.RUNNING,
        completeness=_FAKE_COMPLETENESS,
        # 预期 Python 名（无 alias）字段也能从 dict kwarg 传入
        endpointCount=0,
        callGraphNodeCount=0,
        executionFlowCount=0,
        clusterCount=0,
        findingCount=0,
        createdAt="2025-01-01T00:00:00",
    )
    data = summary.model_dump(by_alias=True)
    assert data["analysisId"] == "ar-1"
    assert data["runStatus"] == "RUNNING"


# ═══════════════════════════════════════════════════════════════════════════════
# EndpointResponse
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndpointResponse:
    """EndpointResponse 构造。"""

    def test_static_endpoint(self) -> None:
        ep = EndpointResponse(
            endpointId="ep-1",
            endpointFingerprint="fp-abc",
            analysisId="ar-1",
            httpMethod="GET",
            normalizedPath="/api/health",
            normalizedPathTemplate="/api/health",
            isTemplated=False,
            pathSegmentCount=2,
        )
        data = ep.model_dump(by_alias=True)
        assert data["httpMethod"] == "GET"
        assert data["normalizedPath"] == "/api/health"
        assert data["isTemplated"] is False

    def test_templated_endpoint(self) -> None:
        ep = EndpointResponse(
            endpointId="ep-2",
            endpointFingerprint="fp-def",
            analysisId="ar-1",
            httpMethod="GET",
            normalizedPath="/users/42",
            normalizedPathTemplate="/users/{id}",
            isTemplated=True,
            pathSegmentCount=2,
            controllerClass="UserController",
            controllerMethod="getUser",
        )
        assert ep.is_templated is True
        assert ep.controller_class == "UserController"


# ═══════════════════════════════════════════════════════════════════════════════
# CallNodeResponse / CallEdgeResponse
# ═══════════════════════════════════════════════════════════════════════════════


def test_call_node_response() -> None:
    node = CallNodeResponse(
        callNodeId="cn-1",
        callNodeFingerprint="fp-node",
        className="com.example.Service",
        methodName="process",
        calleeCount=3,
    )
    data = node.model_dump(by_alias=True)
    assert data["className"] == "com.example.Service"
    assert data["methodName"] == "process"
    assert data["calleeCount"] == 3


def test_call_edge_response() -> None:
    edge = CallEdgeResponse(
        callEdgeId="ce-1",
        fromNodeId="cn-1",
        toNodeId="cn-2",
        toClassName="com.example.Repo",
        toMethodName="save",
        resolutionType="RESOLVED",
        confidence="HIGH",
    )
    data = edge.model_dump(by_alias=True)
    assert data["resolutionType"] == "RESOLVED"
    assert data["confidence"] == "HIGH"


# ═══════════════════════════════════════════════════════════════════════════════
# ExecutionFlowResponse
# ═══════════════════════════════════════════════════════════════════════════════


def test_execution_flow_response() -> None:
    flow = ExecutionFlowResponse(
        executionFlowId="ef-1",
        entryPoint="com.example.Controller.handle",
        callDepth=3,
        steps=[
            ExecutionFlowStepResponse(
                flowStepId="fs-1",
                stepIndex=0,
                depth=0,
                methodKey="com.example.Controller.handle",
                className="com.example.Controller",
                methodName="handle",
            ),
        ],
    )
    data = flow.model_dump(by_alias=True)
    assert data["entryPoint"] == "com.example.Controller.handle"
    assert len(data["steps"]) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# DiagnosticsResponse
# ═══════════════════════════════════════════════════════════════════════════════


def test_diagnostics_response() -> None:
    diag = DiagnosticsResponse(
        totalSourceFiles=120,
        eligibleSourceFiles=100,
        parsedFileCount=90,
        failedFileCount=10,
        failedFiles=["A.java", "B.java"],
        totalCalls=500,
        resolvedHigh=300,
        resolvedMedium=100,
        resolvedLow=50,
        unresolved=50,
        classpathAvailable=True,
        jarCount=30,
        classpathSource="MAVEN",
        classpathWarnings=["unused dep"],
        moduleCount=5,
        applicationModuleCount=2,
    )
    data = diag.model_dump(by_alias=True)
    assert data["eligibleSourceFiles"] == 100
    assert data["parsedFileCount"] == 90
    assert data["classpathAvailable"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 分页包装模型
# ═══════════════════════════════════════════════════════════════════════════════


class TestPageResponses:
    """游标分页包装模型。"""

    def test_analysis_run_list(self) -> None:
        summary = AnalysisRunSummaryResponse(
            analysisId="ar-1",
            taskId="t-1",
            sourceSnapshotId="ss-1",
            runStatus=AnalysisRunStatus.SUCCEEDED,
            completeness=_FAKE_COMPLETENESS,
            endpointCount=0,
            callGraphNodeCount=0,
            executionFlowCount=0,
            clusterCount=0,
            findingCount=0,
            createdAt="2025-01-01T00:00:00",
        )
        page = AnalysisRunListResponse(
            items=[summary],
            total=1,
            hasMore=False,
        )
        data = page.model_dump(by_alias=True)
        assert data["total"] == 1
        assert data["hasMore"] is False

    def test_analysis_run_list_with_cursor(self) -> None:
        summary = AnalysisRunSummaryResponse(
            analysisId="ar-2",
            taskId="t-1",
            sourceSnapshotId="ss-1",
            runStatus=AnalysisRunStatus.FAILED,
            failureCode="RESULT_PROJECTION_FAILED",
            completeness=_FAKE_COMPLETENESS,
            endpointCount=0,
            callGraphNodeCount=0,
            executionFlowCount=0,
            clusterCount=0,
            findingCount=0,
            createdAt="2025-01-01T00:00:00",
        )
        page = AnalysisRunListResponse(
            items=[summary],
            nextCursor="cursor-2",
            total=50,
            hasMore=True,
        )
        data = page.model_dump(by_alias=True)
        assert data["nextCursor"] == "cursor-2"
        assert data["hasMore"] is True

    def test_endpoint_page(self) -> None:
        ep = EndpointResponse(
            endpointId="ep-1",
            endpointFingerprint="fp",
            analysisId="ar-1",
            httpMethod="GET",
            normalizedPath="/api",
            normalizedPathTemplate="/api",
            isTemplated=False,
            pathSegmentCount=1,
        )
        page = EndpointPageResponse(items=[ep], total=1, hasMore=False)
        assert page.total == 1

    def test_call_graph_page(self) -> None:
        edge = CallEdgeResponse(
            callEdgeId="ce-1",
            fromNodeId="cn-1",
            toNodeId="cn-2",
            toClassName="C",
            toMethodName="m",
            resolutionType="RESOLVED",
        )
        page = CallGraphPageResponse(items=[edge], total=1, hasMore=False)
        assert page.total == 1

    def test_call_node_page(self) -> None:
        node = CallNodeResponse(
            callNodeId="cn-1",
            callNodeFingerprint="fp",
            className="C",
            methodName="m",
            calleeCount=0,
        )
        page = CallNodePageResponse(items=[node], total=1, hasMore=False)
        assert page.total == 1

    def test_execution_flow_page(self) -> None:
        flow = ExecutionFlowResponse(
            executionFlowId="ef-1",
            entryPoint="C.m",
            callDepth=1,
        )
        page = ExecutionFlowPageResponse(items=[flow], total=1, hasMore=False)
        assert page.total == 1
