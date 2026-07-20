"""白盒分析数据模型，与 Java DTO 对齐。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MavenConfig:
    """Maven 配置。"""

    auto_detect: bool = True
    generate_classpath: bool = True
    classpath_file: str | None = None
    executable: str | None = None
    settings_xml: str | None = None
    local_repository: str | None = None
    offline: bool = False
    classpath_mode: str = "auto"
    prepare_reactor_artifacts: bool = False


@dataclass
class Endpoint:
    """REST 端点信息。"""

    path: str
    http_method: str
    controller_class: str
    controller_method: str
    parameters: list[str] = field(default_factory=list)
    return_type: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Endpoint:
        return cls(
            path=data.get("path", ""),
            http_method=data.get("httpMethod", ""),
            controller_class=data.get("controllerClass", ""),
            controller_method=data.get("controllerMethod", ""),
            parameters=data.get("parameters", []),
            return_type=data.get("returnType", ""),
        )


@dataclass
class CallEdge:
    """调用图边，携带解析元数据。"""

    to: str = ""
    method_name: str = ""
    type_name: str = ""
    resolution_type: str = "UNRESOLVED"
    confidence: str = "UNKNOWN"
    candidates: list[str] = field(default_factory=list)
    source_file: str = ""
    line: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CallEdge:
        return cls(
            to=data.get("to", ""),
            method_name=data.get("methodName", ""),
            type_name=data.get("typeName", ""),
            resolution_type=data.get("resolutionType", "UNRESOLVED"),
            confidence=data.get("confidence", "UNKNOWN"),
            candidates=data.get("candidates", []),
            source_file=data.get("sourceFile", ""),
            line=data.get("line", 0),
        )


@dataclass
class CallGraphNode:
    """调用图节点。"""

    class_name: str
    method_name: str
    method_signature: str
    callee_details: list[CallEdge] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CallGraphNode:
        return cls(
            class_name=data.get("className", ""),
            method_name=data.get("methodName", ""),
            method_signature=data.get("methodSignature", ""),
            callee_details=[CallEdge.from_dict(ce) for ce in data.get("calleeDetails", [])],
        )


@dataclass
class CallGraph:
    """调用图，key 为 className#methodName。"""

    nodes: dict[str, CallGraphNode] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CallGraph:
        return cls(
            nodes={key: CallGraphNode.from_dict(node) for key, node in data.items()},
        )


@dataclass
class ParseFailureDetail:
    """单个文件解析失败详情。"""

    file: str = ""
    problems: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParseFailureDetail:
        return cls(
            file=data.get("file", ""),
            problems=data.get("problems", []),
        )


@dataclass
class AnalyzerDiagnostics:
    """分析诊断信息。"""

    total_source_files: int = 0
    parsed_file_count: int = 0
    failed_file_count: int = 0
    failed_files: list[ParseFailureDetail] = field(default_factory=list)
    total_calls: int = 0
    resolved_high: int = 0
    resolved_medium: int = 0
    resolved_low: int = 0
    unresolved: int = 0
    classpath_available: bool = False
    jar_count: int = 0
    classpath_source: str = ""
    classpath_warnings: list[str] = field(default_factory=list)
    classpath_errors: list[str] = field(default_factory=list)
    classpath_command: str = ""
    classpath_exit_code: int | None = None
    classpath_duration_ms: int | None = None
    classpath_stdout_tail: str = ""
    classpath_stderr_tail: str = ""
    classpath_timed_out: bool = False
    application_module_count: int = 0
    business_module_count: int = 0
    library_module_count: int = 0
    bom_module_count: int = 0
    module_types: dict[str, str] = field(default_factory=dict)
    # P0/P3: Maven 模块信息（与 Java 端 AnalyzerDiagnostics 对齐）
    root_pom: str = ""
    module_count: int = 0
    source_root_count: int = 0
    modules: list[str] = field(default_factory=list)
    # P3: classpath 模块明细
    classpath_target_modules: list[str] = field(default_factory=list)
    classpath_failed_modules: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalyzerDiagnostics:
        return cls(
            total_source_files=data.get("totalSourceFiles", 0),
            parsed_file_count=data.get("parsedFileCount", 0),
            failed_file_count=data.get("failedFileCount", 0),
            failed_files=[
                ParseFailureDetail.from_dict(ff) for ff in (data.get("failedFiles") or [])
            ],
            total_calls=data.get("totalCalls", 0),
            resolved_high=data.get("resolvedHigh", 0),
            resolved_medium=data.get("resolvedMedium", 0),
            resolved_low=data.get("resolvedLow", 0),
            unresolved=data.get("unresolved", 0),
            classpath_available=data.get("classpathAvailable", False),
            jar_count=data.get("jarCount", 0),
            classpath_source=data.get("classpathSource", ""),
            classpath_warnings=data.get("classpathWarnings", []),
            classpath_errors=data.get("classpathErrors", []),
            classpath_command=data.get("classpathCommand", ""),
            classpath_exit_code=data.get("classpathExitCode"),
            classpath_duration_ms=data.get("classpathDurationMs"),
            classpath_stdout_tail=data.get("classpathStdoutTail", ""),
            classpath_stderr_tail=data.get("classpathStderrTail", ""),
            classpath_timed_out=data.get("classpathTimedOut", False),
            application_module_count=data.get("applicationModuleCount", 0),
            business_module_count=data.get("businessModuleCount", 0),
            library_module_count=data.get("libraryModuleCount", 0),
            bom_module_count=data.get("bomModuleCount", 0),
            module_types=data.get("moduleTypes", {}),
            root_pom=data.get("rootPom", ""),
            module_count=data.get("moduleCount", 0),
            source_root_count=data.get("sourceRootCount", 0),
            modules=data.get("modules", []),
            classpath_target_modules=data.get("classpathTargetModules", []),
            classpath_failed_modules=data.get("classpathFailedModules", []),
        )


@dataclass
class WhiteboxJobEvent:
    """Java 分析作业进度事件。"""

    timestamp: str = ""
    stage: str = ""
    level: str = ""
    message: str = ""


@dataclass
class WhiteboxJobStatus:
    """Java 分析作业状态。"""

    job_id: str = ""
    status: str = ""
    stage: str = ""
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    events: list[WhiteboxJobEvent] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WhiteboxJobStatus:
        return cls(
            job_id=data.get("jobId", ""),
            status=data.get("status", ""),
            stage=data.get("stage", ""),
            created_at=data.get("createdAt", ""),
            started_at=data.get("startedAt"),
            finished_at=data.get("finishedAt"),
            error=data.get("error"),
            events=[
                WhiteboxJobEvent(
                    timestamp=e.get("timestamp", ""),
                    stage=e.get("stage", ""),
                    level=e.get("level", ""),
                    message=e.get("message", ""),
                )
                for e in data.get("events", [])
            ],
        )


@dataclass
class WhiteboxFinding:
    """白盒代码缺陷/坏味道。"""

    rule_id: str
    severity: str
    title: str
    description: str
    file_path: str
    line_number: int
    snippet: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WhiteboxFinding:
        return cls(
            rule_id=data.get("ruleId", ""),
            severity=data.get("severity", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            file_path=data.get("filePath", ""),
            line_number=data.get("lineNumber", 0),
            snippet=data.get("snippet", ""),
        )


@dataclass
class FlowStep:
    """执行流中的一步。"""

    depth: int = 0
    method_key: str = ""
    class_name: str = ""
    method_name: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowStep:
        return cls(
            depth=data.get("depth", 0),
            method_key=data.get("methodKey", ""),
            class_name=data.get("className", ""),
            method_name=data.get("methodName", ""),
        )


@dataclass
class ExecutionFlow:
    """从端点入口开始的完整调用链。"""

    entry_point: str = ""
    steps: list[FlowStep] = field(default_factory=list)
    call_depth: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionFlow:
        return cls(
            entry_point=data.get("entryPoint", ""),
            steps=[FlowStep.from_dict(s) for s in data.get("steps", [])],
            call_depth=data.get("callDepth", 0),
        )


@dataclass
class ClusterInfo:
    """功能聚类分组。"""

    cluster_id: str = ""
    suggested_label: str = ""
    member_keys: list[str] = field(default_factory=list)
    member_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClusterInfo:
        return cls(
            cluster_id=data.get("clusterId", ""),
            suggested_label=data.get("suggestedLabel", ""),
            member_keys=data.get("memberKeys", []),
            member_count=data.get("memberCount", 0),
        )


@dataclass
class WhiteboxResult:
    """白盒分析结果。"""

    endpoints: list[Endpoint] = field(default_factory=list)
    call_graph: CallGraph = field(default_factory=CallGraph)
    findings: list[WhiteboxFinding] = field(default_factory=list)
    execution_flows: list[ExecutionFlow] = field(default_factory=list)
    clusters: list[ClusterInfo] = field(default_factory=list)
    diagnostics: AnalyzerDiagnostics | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WhiteboxResult:
        """从 Java API 响应的 JSON dict 反序列化。"""
        raw_diag = data.get("diagnostics")
        return cls(
            endpoints=[Endpoint.from_dict(e) for e in data.get("endpoints", [])],
            call_graph=CallGraph.from_dict(data.get("callGraph", {})),
            findings=[WhiteboxFinding.from_dict(f) for f in data.get("findings", [])],
            execution_flows=[ExecutionFlow.from_dict(ef) for ef in data.get("executionFlows", [])],
            clusters=[ClusterInfo.from_dict(c) for c in data.get("clusters", [])],
            diagnostics=AnalyzerDiagnostics.from_dict(raw_diag) if raw_diag else None,
        )
