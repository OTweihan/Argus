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

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "autoDetect": self.auto_detect,
            "generateClasspath": self.generate_classpath,
            "offline": self.offline,
        }
        if self.classpath_file is not None:
            d["classpathFile"] = self.classpath_file
        if self.executable is not None:
            d["executable"] = self.executable
        if self.settings_xml is not None:
            d["settingsXml"] = self.settings_xml
        if self.local_repository is not None:
            d["localRepository"] = self.local_repository
        if self.classpath_mode != "auto":
            d["classpathMode"] = self.classpath_mode
        if self.prepare_reactor_artifacts:
            d["prepareReactorArtifacts"] = True
        return d


@dataclass
class Endpoint:
    """REST 端点信息。"""

    path: str
    http_method: str
    controller_class: str
    controller_method: str
    parameters: list[str] = field(default_factory=list)
    return_type: str = ""


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


@dataclass
class CallGraphNode:
    """调用图节点。"""

    class_name: str
    method_name: str
    method_signature: str
    callee_details: list[CallEdge] = field(default_factory=list)


@dataclass
class CallGraph:
    """调用图，key 为 className#methodName。"""

    nodes: dict[str, CallGraphNode] = field(default_factory=dict)


@dataclass
class ParseFailureDetail:
    """单个文件解析失败详情。"""

    file: str = ""
    problems: list[str] = field(default_factory=list)


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


@dataclass
class FlowStep:
    """执行流中的一步。"""

    depth: int = 0
    method_key: str = ""
    class_name: str = ""
    method_name: str = ""


@dataclass
class ExecutionFlow:
    """从端点入口开始的完整调用链。"""

    entry_point: str = ""
    steps: list[FlowStep] = field(default_factory=list)
    call_depth: int = 0


@dataclass
class ClusterInfo:
    """功能聚类分组。"""

    cluster_id: str = ""
    suggested_label: str = ""
    member_keys: list[str] = field(default_factory=list)
    member_count: int = 0


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
        endpoints = [
            Endpoint(
                path=e.get("path", ""),
                http_method=e.get("httpMethod", ""),
                controller_class=e.get("controllerClass", ""),
                controller_method=e.get("controllerMethod", ""),
                parameters=e.get("parameters", []),
                return_type=e.get("returnType", ""),
            )
            for e in data.get("endpoints", [])
        ]

        raw_nodes = data.get("callGraph", {})
        nodes = {}
        for key, node in raw_nodes.items():
            callee_details = [
                CallEdge(
                    to=ce.get("to", ""),
                    method_name=ce.get("methodName", ""),
                    type_name=ce.get("typeName", ""),
                    resolution_type=ce.get("resolutionType", "UNRESOLVED"),
                    confidence=ce.get("confidence", "UNKNOWN"),
                    candidates=ce.get("candidates", []),
                    source_file=ce.get("sourceFile", ""),
                    line=ce.get("line", 0),
                )
                for ce in node.get("calleeDetails", [])
            ]
            nodes[key] = CallGraphNode(
                class_name=node.get("className", ""),
                method_name=node.get("methodName", ""),
                method_signature=node.get("methodSignature", ""),
                callee_details=callee_details,
            )
        call_graph = CallGraph(nodes=nodes)

        findings = [
            WhiteboxFinding(
                rule_id=f.get("ruleId", ""),
                severity=f.get("severity", ""),
                title=f.get("title", ""),
                description=f.get("description", ""),
                file_path=f.get("filePath", ""),
                line_number=f.get("lineNumber", 0),
                snippet=f.get("snippet", ""),
            )
            for f in data.get("findings", [])
        ]

        execution_flows = [
            ExecutionFlow(
                entry_point=ef.get("entryPoint", ""),
                steps=[
                    FlowStep(
                        depth=s.get("depth", 0),
                        method_key=s.get("methodKey", ""),
                        class_name=s.get("className", ""),
                        method_name=s.get("methodName", ""),
                    )
                    for s in ef.get("steps", [])
                ],
                call_depth=ef.get("callDepth", 0),
            )
            for ef in data.get("executionFlows", [])
        ]

        clusters = [
            ClusterInfo(
                cluster_id=c.get("clusterId", ""),
                suggested_label=c.get("suggestedLabel", ""),
                member_keys=c.get("memberKeys", []),
                member_count=c.get("memberCount", 0),
            )
            for c in data.get("clusters", [])
        ]

        raw_diag = data.get("diagnostics")
        diagnostics = None
        if raw_diag:
            failed_files = [
                ParseFailureDetail(
                    file=ff.get("file", ""),
                    problems=ff.get("problems", []),
                )
                for ff in (raw_diag.get("failedFiles") or [])
            ]
            diagnostics = AnalyzerDiagnostics(
                total_source_files=raw_diag.get("totalSourceFiles", 0),
                parsed_file_count=raw_diag.get("parsedFileCount", 0),
                failed_file_count=raw_diag.get("failedFileCount", 0),
                failed_files=failed_files,
                total_calls=raw_diag.get("totalCalls", 0),
                resolved_high=raw_diag.get("resolvedHigh", 0),
                resolved_medium=raw_diag.get("resolvedMedium", 0),
                resolved_low=raw_diag.get("resolvedLow", 0),
                unresolved=raw_diag.get("unresolved", 0),
                classpath_available=raw_diag.get("classpathAvailable", False),
                jar_count=raw_diag.get("jarCount", 0),
                classpath_source=raw_diag.get("classpathSource", ""),
                classpath_warnings=raw_diag.get("classpathWarnings", []),
                classpath_errors=raw_diag.get("classpathErrors", []),
                classpath_command=raw_diag.get("classpathCommand", ""),
                classpath_exit_code=raw_diag.get("classpathExitCode"),
                classpath_duration_ms=raw_diag.get("classpathDurationMs"),
                classpath_stdout_tail=raw_diag.get("classpathStdoutTail", ""),
                classpath_stderr_tail=raw_diag.get("classpathStderrTail", ""),
                classpath_timed_out=raw_diag.get("classpathTimedOut", False),
                application_module_count=raw_diag.get("applicationModuleCount", 0),
                business_module_count=raw_diag.get("businessModuleCount", 0),
                library_module_count=raw_diag.get("libraryModuleCount", 0),
                bom_module_count=raw_diag.get("bomModuleCount", 0),
                module_types=raw_diag.get("moduleTypes", {}),
            )

        return cls(
            endpoints=endpoints,
            call_graph=call_graph,
            findings=findings,
            execution_flows=execution_flows,
            clusters=clusters,
            diagnostics=diagnostics,
        )
