"""白盒结果映射与序列化 — 纯函数，无 IO。

两套对 ``WhiteboxResult`` 的字段映射集中于此：
- ``map_findings``：Java findings → 业务 Finding 实体（task.findings 持久化用）；
- ``build_projection_data``：WhiteboxResult → 结构化投影行（analysis_* 表）；
- ``serialize_whitebox_result`` / ``evaluate_completeness``：结果 JSON 序列化
  （result_json 审计留存 + 报告模板渲染）。
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from argus_py.analysis.enums import (
    CompletenessStatus,
    QualityIssueCode,
    QualityIssueLevel,
)
from argus_py.core.enums import FindingSeverity, FindingType
from argus_py.whitebox.models import (
    AnalyzerDiagnostics,
    WhiteboxFinding,
    WhiteboxResult,
)


def map_severity(severity: str) -> FindingSeverity:
    """将 Java 端的严重级别映射到 FindingSeverity。"""
    mapping = {
        "CRITICAL": FindingSeverity.CRITICAL,
        "HIGH": FindingSeverity.HIGH,
        "MEDIUM": FindingSeverity.MEDIUM,
        "LOW": FindingSeverity.LOW,
        "INFO": FindingSeverity.INFO,
    }
    return mapping.get(severity.upper(), FindingSeverity.INFO)


def map_finding_type(rule_category: str | None) -> FindingType:
    """从 RuleCategory 枚举做确定性映射到 FindingType。

    不做 severity 推导、不做 rule_id 前缀猜测。
    """
    if not rule_category:
        return FindingType.UNKNOWN
    mapping: dict[str, FindingType] = {
        "SECURITY": FindingType.SECURITY,
        "BUG": FindingType.FUNCTIONAL,
        "PERFORMANCE": FindingType.PERFORMANCE,
        "STYLE": FindingType.STYLE,
        "CODE_SMELL": FindingType.CODE_QUALITY,
        "UNKNOWN": FindingType.UNKNOWN,
    }
    return mapping.get(rule_category.upper(), FindingType.UNKNOWN)


def compute_fingerprint(
    rule_id: str | None,
    file_path: str,
    line_number: int,
    title: str,
    source_root: str | None = None,
) -> str:
    """生成 Finding 的稳定指纹。

    尝试将 file_path 转换为源码根目录相对路径以实现跨执行一致性。
    """
    normalized_path: str
    if source_root:
        try:
            relative = Path(file_path).resolve().relative_to(Path(source_root).resolve())
            normalized_path = PurePosixPath(relative).as_posix()
        except (ValueError, OSError):
            normalized_path = file_path.replace("\\", "/").strip()
    else:
        normalized_path = file_path.replace("\\", "/").strip()

    return sha256(
        "\0".join(
            [
                rule_id or "",
                normalized_path,
                str(line_number),
                title.strip(),
            ]
        ).encode()
    ).hexdigest()


def map_findings(
    whitebox_findings: list[WhiteboxFinding],
    source_root: str | None = None,
    analysis_id: str = "",
) -> list[Any]:
    """将 WhiteboxFinding 列表映射到业务层 Finding 列表。

    rule_category / analysis_confidence 由 Java 返回，Python 不做推导。
    snippet / analysis_id 透传到 Finding 持久化字段。
    源码定位以 file_path + line_number 为唯一权威（start_line 必须 >=1）；
    相同 fingerprint 的去重。
    """
    from argus_py.task.models import Finding

    findings: list[Finding] = []
    seen: set[str] = set()
    for wf in whitebox_findings:
        has_valid_location = bool(wf.file_path and wf.line_number and wf.line_number >= 1)
        location = (
            f"{wf.file_path}:{wf.line_number}"
            if has_valid_location
            else (wf.file_path or "(unknown)")
        )
        # fingerprint 仅在位置有效时计算（跨执行稳定）
        fp = None
        if has_valid_location:
            fp = compute_fingerprint(
                wf.rule_id,
                wf.file_path,
                wf.line_number,
                wf.title,
                source_root=source_root,
            )
            if fp in seen:
                continue
            seen.add(fp)

        finding = Finding(
            title=wf.title,
            description=wf.description,
            severity=map_severity(wf.severity),
            finding_type=map_finding_type(wf.rule_category),
            location=location,
            rule_id=wf.rule_id,
            rule_category=wf.rule_category,
            confidence=wf.analysis_confidence,
            fingerprint=fp,
            snippet=wf.snippet,
            analysis_id=analysis_id,
        )
        findings.append(finding)
    return findings


def build_projection_data(result: WhiteboxResult, *, analysis_id: str) -> dict[str, Any]:
    """从 WhiteboxResult 构造结构化投影数据（供 complete_projection 使用）。

    实体 ID 以 analysis_id 为前缀，确保跨分析的全局唯一性，
    避免不同分析对相同代码生成相同 ID 时 INSERT OR REPLACE 覆盖旧记录。
    注：完整的 UUID v5 确定性 ID（基于 fingerprint）在 Java 端提供
    endpoint_fingerprint / call_node_fingerprint 后再迁移。
    """
    aid = analysis_id

    # CallNode
    call_nodes: list[dict[str, Any]] = []
    for key, node in result.call_graph.nodes.items():
        call_nodes.append(
            {
                "call_node_id": f"{aid}:cn:{key}",
                "call_node_fingerprint": f"fp:cn:{key}",
                "class_name": node.class_name,
                "method_name": node.method_name,
                "method_signature": node.method_signature,
                # source_* 列保留：Java CallGraphNode 暂未返回源码位置，恒为 NULL。
                # 0002 迁移 FORWARD-ONLY 不可 DROP，待 Java 端补充后再填充。
                "source_file": None,
                "source_start_line": None,
                "source_start_column": None,
                "source_end_line": None,
                "source_end_column": None,
            }
        )

    # CallEdge — 加枚举索引防止同名重载碰撞
    call_edges: list[dict[str, Any]] = []
    for key, node in result.call_graph.nodes.items():
        for i, edge in enumerate(node.callee_details):
            # to_node_id 为空的 edge 跳过（无引用目标）
            if not edge.to:
                continue
            call_edges.append(
                {
                    "call_edge_id": f"{aid}:ce:{key}:{i}",
                    "from_node_id": f"{aid}:cn:{key}",
                    "to_node_id": f"{aid}:cn:{edge.to}",
                    "to_class_name": edge.type_name or None,
                    "to_method_name": edge.method_name or None,
                    "resolution_type": edge.resolution_type,
                    "confidence": edge.confidence,
                    "source_file": edge.source_file or None,
                    "source_start_line": edge.line if edge.line > 0 else None,
                    "source_start_column": None,
                    "source_end_line": None,
                    "source_end_column": None,
                }
            )

    # ExecutionFlow
    # Java ExecutionFlowTracer 按端点生成执行流；多个端点共享同一 controller
    # 方法时（如 @RequestMapping 多路径/多方法映射），会产生 entry_point 相同的
    # 多条流（步骤内容完全一致）。而 analysis_execution_flows 唯一约束为
    # (analysis_id, execution_flow_fingerprint)——同一分析内指纹必须唯一，
    # 这里按 entry_point 去重、只保留首条，避免 UNIQUE 冲突导致投影事务整体回滚。
    execution_flows: list[dict[str, Any]] = []
    flow_steps: list[dict[str, Any]] = []
    seen_flow_keys: set[str] = set()
    for flow in result.execution_flows:
        fid = f"{aid}:ef:{flow.entry_point}"
        if flow.entry_point in seen_flow_keys:
            continue
        seen_flow_keys.add(flow.entry_point)
        execution_flows.append(
            {
                "execution_flow_id": fid,
                "execution_flow_fingerprint": fid,
                "entry_point": flow.entry_point,
                "call_depth": flow.call_depth,
            }
        )
        for i, step in enumerate(flow.steps):
            # FlowStep.method_key 与 CallGraph key 格式同为 "className#methodName"
            # (Java 端 DTO 契约保证)，因此 call_node_id 直接引用 cn:{method_key}
            flow_steps.append(
                {
                    "flow_step_id": f"fs:{fid}:{i}",
                    "execution_flow_id": fid,
                    "step_index": i,
                    "depth": step.depth,
                    "method_key": step.method_key,
                    "class_name": step.class_name or None,
                    "method_name": step.method_name or None,
                    "call_node_id": f"{aid}:cn:{step.method_key}",
                }
            )

    # Endpoint
    # source_* 列保留：Java EndpointInfo 暂未返回源码位置，恒为 NULL。
    # 0002 迁移 FORWARD-ONLY 不可 DROP，待 Java 端补充后再填充。
    endpoints: list[dict[str, Any]] = []
    for ep in result.endpoints:
        endpoints.append(
            {
                "endpoint_id": f"{aid}:ep:{ep.http_method}:{ep.path}",
                "endpoint_fingerprint": f"fp:{ep.http_method}:{ep.path}",
                "http_method": ep.http_method,
                "raw_path": ep.path,
                "normalized_exact_path": ep.path if "{" not in ep.path else None,
                "normalized_path_template": ep.path,
                "is_templated": "{" in ep.path,
                "path_normalization_version": 1,
                "path_segment_count": len([s for s in ep.path.split("/") if s]),
                "controller_class": ep.controller_class or None,
                "controller_method": ep.controller_method or None,
                "controller_method_signature": None,
                "parameters": ep.parameters,
                "return_type": ep.return_type or None,
                "source_file": None,
                "source_start_line": None,
                "source_start_column": None,
                "source_end_line": None,
                "source_end_column": None,
                "entry_call_node_id": None,
            }
        )

    # Diagnostics
    diag = result.diagnostics
    diagnostics = None
    if diag:
        diagnostics = {
            "total_source_files": diag.total_source_files,
            # Java 端 SourceFileScanner 的 totalFiles 已经过滤为可扫描 .java 文件，
            # 当前 eligible_source_files 与 total_source_files 等价。
            # 待 Java 端新增 eligibleSourceFiles 字段（排除测试/生成代码等）后区分。
            "eligible_source_files": diag.total_source_files,
            "parsed_file_count": diag.parsed_file_count,
            "failed_file_count": diag.failed_file_count,
            "failed_files": [pf.file for pf in diag.failed_files],
            "total_calls": diag.total_calls,
            "resolved_high": diag.resolved_high,
            "resolved_medium": diag.resolved_medium,
            "resolved_low": diag.resolved_low,
            "unresolved": diag.unresolved,
            "classpath_available": diag.classpath_available,
            "jar_count": diag.jar_count,
            "classpath_source": diag.classpath_source or None,
            "classpath_warnings": diag.classpath_warnings,
            "classpath_errors": diag.classpath_errors,
            "module_count": diag.module_count,
            "application_module_count": diag.application_module_count,
        }

    # Clusters
    clusters: list[dict[str, Any]] = []
    for c in result.clusters:
        clusters.append(
            {
                "cluster_id": f"{aid}:cl:{c.cluster_id}",
                "suggested_label": c.suggested_label or "",
                "member_keys": c.member_keys or [],
                "member_count": c.member_count,
            }
        )

    return {
        "call_nodes": call_nodes,
        "call_edges": call_edges,
        "execution_flows": execution_flows,
        "flow_steps": flow_steps,
        "endpoints": endpoints,
        "clusters": clusters,
        "diagnostics": diagnostics,
    }


def evaluate_completeness(
    diagnostics: AnalyzerDiagnostics | None,
) -> tuple[str, list[dict[str, Any]]]:
    """从诊断信息评估分析完整性，返回（completeness_status, quality_issues）。

    供投影持久化与报告序列化共用：报告层与控制台一致地醒目呈现降级，
    不再依赖模板从诊断数字间接推断。
    """
    if diagnostics is None:
        # Java 未返回 diagnostics → 无法评估，标记 NOT_EVALUATED
        return CompletenessStatus.NOT_EVALUATED.value, []

    diag = diagnostics
    quality_issues: list[dict[str, Any]] = []

    if diag.total_source_files == 0:
        return CompletenessStatus.UNAVAILABLE.value, [
            {
                "code": QualityIssueCode.NO_ELIGIBLE_SOURCE_FILES.value,
                "level": QualityIssueLevel.ERROR.value,
                "message": "无可分析源文件",
                "affectedCount": 0,
                "totalCount": 0,
            }
        ]

    completeness = CompletenessStatus.COMPLETE.value

    if diag.failed_file_count > 0:
        completeness = CompletenessStatus.DEGRADED.value
        quality_issues.append(
            {
                "code": QualityIssueCode.MODULE_PARSE_PARTIAL_FAILURE.value,
                "level": QualityIssueLevel.WARNING.value,
                "message": (
                    f"源文件解析部分失败: "
                    f"{diag.parsed_file_count}/{diag.total_source_files} 成功, "
                    f"{diag.failed_file_count} 失败"
                ),
                "affectedCount": diag.failed_file_count,
                "totalCount": diag.total_source_files,
            }
        )
    if not diag.classpath_available:
        completeness = CompletenessStatus.DEGRADED.value
        quality_issues.append(
            {
                "code": QualityIssueCode.CLASSPATH_UNAVAILABLE.value,
                "level": QualityIssueLevel.WARNING.value,
                "message": "Classpath 不可用，调用解析降级为源码分析",
                "affectedCount": diag.total_calls,
                "totalCount": diag.total_calls,
            }
        )
    elif diag.classpath_errors:
        completeness = CompletenessStatus.DEGRADED.value
        quality_issues.append(
            {
                "code": QualityIssueCode.CLASSPATH_DEGRADED.value,
                "level": QualityIssueLevel.WARNING.value,
                "message": (f"Classpath 部分解析失败: {len(diag.classpath_errors)} 个 JAR 不可用"),
                "affectedCount": len(diag.classpath_errors),
                "totalCount": diag.jar_count,
            }
        )
    elif diag.resolved_high + diag.resolved_medium < diag.total_calls:
        completeness = CompletenessStatus.DEGRADED.value
        quality_issues.append(
            {
                "code": QualityIssueCode.CALL_RESOLUTION_LOW.value,
                "level": QualityIssueLevel.WARNING.value,
                "message": (
                    f"调用解析置信度偏低: "
                    f"高 {diag.resolved_high}, 中 {diag.resolved_medium}, "
                    f"低 {diag.resolved_low}, 未解析 {diag.unresolved}"
                ),
                "affectedCount": diag.resolved_low + diag.unresolved,
                "totalCount": diag.total_calls,
            }
        )

    # O-11：可选 AnalysisPass 失败时 Java 显式记录 passFailures；此处消费使
    # 降级对用户可见（完整性与 CLI/报告降级徽标据此触发），而非静默。
    if diag.pass_failures:
        completeness = CompletenessStatus.DEGRADED.value
        quality_issues.append(
            {
                "code": QualityIssueCode.ANALYSIS_PASS_FAILED.value,
                "level": QualityIssueLevel.WARNING.value,
                "message": "分析子任务失败，结果已降级: " + "；".join(diag.pass_failures),
                "affectedCount": len(diag.pass_failures),
                "totalCount": len(diag.pass_failures),
            }
        )

    return completeness, quality_issues


def serialize_whitebox_result(
    result: WhiteboxResult,
    endpoint_count: int,
    finding_count: int,
    scope: str,
) -> dict:
    """将 WhiteboxResult 序列化为可 JSON 序列化的字典（供报告模板和审计留存使用）。

    序列化全部结果数据（endpoints / callGraph / executionFlows / clusters /
    diagnostics / findings / summary）及完整性结论（completeness / qualityIssues），
    确保 raw_result_json 作为完整的审计数据源，报告模板可直接渲染降级横幅。"""
    completeness, quality_issues = evaluate_completeness(result.diagnostics)
    return {
        "completeness": completeness,
        "qualityIssues": quality_issues,
        "endpoints": [
            {
                "path": e.path,
                "httpMethod": e.http_method,
                "controllerClass": e.controller_class,
                "controllerMethod": e.controller_method,
                "parameters": e.parameters,
                "returnType": e.return_type,
            }
            for e in result.endpoints
        ],
        "callGraph": {
            key: {
                "className": node.class_name,
                "methodName": node.method_name,
                "methodSignature": node.method_signature,
                "calleeDetails": [
                    {
                        "to": ce.to,
                        "methodName": ce.method_name,
                        "typeName": ce.type_name,
                        "resolutionType": ce.resolution_type,
                        "confidence": ce.confidence,
                        "candidates": ce.candidates,
                        "sourceFile": ce.source_file,
                        "line": ce.line,
                    }
                    for ce in node.callee_details
                ],
            }
            for key, node in result.call_graph.nodes.items()
        },
        "executionFlows": [
            {
                "entryPoint": ef.entry_point,
                "callDepth": ef.call_depth,
                "steps": [
                    {
                        "depth": s.depth,
                        "methodKey": s.method_key,
                        "className": s.class_name,
                        "methodName": s.method_name,
                    }
                    for s in ef.steps
                ],
            }
            for ef in result.execution_flows
        ],
        "clusters": [
            {
                "clusterId": c.cluster_id,
                "suggestedLabel": c.suggested_label,
                "memberKeys": c.member_keys,
                "memberCount": c.member_count,
            }
            for c in result.clusters
        ],
        "findings": [
            {
                "ruleId": f.rule_id,
                "severity": f.severity,
                "title": f.title,
                "description": f.description,
                "filePath": f.file_path,
                "lineNumber": f.line_number,
                "snippet": f.snippet,
                "ruleCategory": f.rule_category,
                "analysisConfidence": f.analysis_confidence,
            }
            for f in result.findings
        ],
        "diagnostics": (
            {
                "totalSourceFiles": result.diagnostics.total_source_files,
                "parsedFileCount": result.diagnostics.parsed_file_count,
                "failedFileCount": result.diagnostics.failed_file_count,
                "failedFiles": [
                    {"file": ff.file, "problems": ff.problems}
                    for ff in result.diagnostics.failed_files
                ],
                "totalCalls": result.diagnostics.total_calls,
                "resolvedHigh": result.diagnostics.resolved_high,
                "resolvedMedium": result.diagnostics.resolved_medium,
                "resolvedLow": result.diagnostics.resolved_low,
                "unresolved": result.diagnostics.unresolved,
                "classpathAvailable": result.diagnostics.classpath_available,
                "jarCount": result.diagnostics.jar_count,
                "classpathSource": result.diagnostics.classpath_source,
                "classpathWarnings": result.diagnostics.classpath_warnings,
                "classpathErrors": result.diagnostics.classpath_errors,
                "applicationModuleCount": result.diagnostics.application_module_count,
                "businessModuleCount": result.diagnostics.business_module_count,
                "libraryModuleCount": result.diagnostics.library_module_count,
                "bomModuleCount": result.diagnostics.bom_module_count,
                "moduleTypes": result.diagnostics.module_types,
                # O-11：可选 pass 降级记录（与 Java AnalyzerDiagnostics.passFailures 对齐）
                "passFailures": result.diagnostics.pass_failures,
                # flows pass 步数预算截断记录（与 Java flowTruncations 对齐）
                "flowTruncations": result.diagnostics.flow_truncations,
            }
            if result.diagnostics
            else None
        ),
        "summary": {
            "endpoint_count": endpoint_count,
            "call_graph_node_count": len(result.call_graph.nodes),
            "finding_count": finding_count,
            "execution_flow_count": len(result.execution_flows),
            "cluster_count": len(result.clusters),
            "scope": scope,
        },
    }
