"""白盒任务执行器。"""

from __future__ import annotations

import logging

from argus_py.core.enums import FindingSeverity, FindingType
from argus_py.observability.context import run_in_thread
from argus_py.task.models import Finding, Task
from argus_py.whitebox.client import WhiteboxClient
from argus_py.whitebox.models import AnalyzerDiagnostics, WhiteboxFinding, WhiteboxResult
from argus_py.whitebox.source_resolver import SourceResolver

logger = logging.getLogger(__name__)


class WhiteboxRunner:
    """白盒分析任务执行器。

    编排：SourceResolver → WhiteboxClient.analyze → 写 Findings/产物
    """

    def __init__(
        self,
        client: WhiteboxClient | None = None,
        source_resolver: SourceResolver | None = None,
    ) -> None:
        self._client = client or WhiteboxClient()
        self._source_resolver = source_resolver or SourceResolver()

    async def run(self, task: Task) -> Task:
        """执行白盒分析任务。

        Parameters
        ----------
        task : Task
            需要包含 ``parameters.repo_url`` 或 ``parameters.source_path``，
            以及可选的 ``parameters.scope``、``parameters.branch``。

        Returns
        -------
        Task
            更新后的任务，包含 Findings 和 result_summary。
        """
        params = task.parameters or {}
        repo_url: str | None = params.get("repo_url")
        source_path: str | None = params.get("source_path")
        scope: str = params.get("scope", "all")
        branch: str | None = params.get("branch")
        maven: dict | None = params.get("maven")

        if not repo_url and not source_path:
            raise ValueError("parameters 必须包含 repo_url 或 source_path")

        try:
            # Step 1: 解析源码（在 IO 线程执行，不阻塞事件循环）
            if repo_url:
                if branch:
                    resolved_path = await run_in_thread(
                        self._source_resolver.resolve, repo_url, branch
                    )
                else:
                    resolved_path = await run_in_thread(self._source_resolver.resolve, repo_url)
            else:
                assert source_path is not None  # 已在入口处校验
                resolved_path = await run_in_thread(
                    self._source_resolver.resolve_path, source_path
                )

            # Step 2: 调用 Java 分析服务
            logger.info("开始白盒分析: path=%s scope=%s", resolved_path, scope)
            result = await self._client.analyze(resolved_path, scope=scope, maven=maven)

            # Step 3: 写 Findings
            task.findings = _map_findings(result.findings)

            # Step 4: 设置结果摘要
            endpoint_count = len(result.endpoints)
            finding_count = len(result.findings)
            diag_summary = _build_diag_summary(result.diagnostics)
            task.result_summary = (
                f"白盒分析完成。发现 {endpoint_count} 个端点、"
                f"{finding_count} 个代码缺陷/坏味道。"
                f"{diag_summary}"
            )

            # 保存全量分析结果至 parameters（报告模板使用）
            task.parameters = {
                **(task.parameters or {}),
                "_whitebox_result": _serialize_whitebox_result(
                    result, endpoint_count, finding_count, scope
                ),
            }

            logger.info(
                "白盒分析完成: endpoints=%d callgraph_nodes=%d findings=%d flows=%d clusters=%d",
                endpoint_count,
                len(result.call_graph.nodes),
                finding_count,
                len(result.execution_flows),
                len(result.clusters),
            )
        finally:
            await run_in_thread(self._source_resolver.cleanup)

        return task


def _map_severity(severity: str) -> FindingSeverity:
    """将 Java 端的严重级别映射到 FindingSeverity。"""
    mapping = {
        "CRITICAL": FindingSeverity.CRITICAL,
        "HIGH": FindingSeverity.HIGH,
        "MEDIUM": FindingSeverity.MEDIUM,
        "LOW": FindingSeverity.LOW,
        "INFO": FindingSeverity.INFO,
    }
    return mapping.get(severity.upper(), FindingSeverity.INFO)


def _map_findings(whitebox_findings: list[WhiteboxFinding]) -> list[Finding]:
    """将 WhiteboxFinding 列表映射到业务层 Finding 列表。"""
    findings = []
    for wf in whitebox_findings:
        finding = Finding(
            title=wf.title,
            description=wf.description,
            severity=_map_severity(wf.severity),
            finding_type=(
                FindingType.SECURITY
                if wf.severity.upper() in ("HIGH", "CRITICAL")
                else FindingType.FUNCTIONAL
            ),
            location=f"{wf.file_path}:{wf.line_number}",
        )
        findings.append(finding)
    return findings


def _build_diag_summary(diagnostics: AnalyzerDiagnostics | None) -> str:
    """从诊断信息构建可读的摘要字符串。"""
    if not diagnostics:
        return ""
    cp_info = ""
    if diagnostics.classpath_available:
        cp_info = f"，classpath {diagnostics.jar_count} 个 JAR"
    elif diagnostics.classpath_source:
        cp_info = "，无 classpath（降级为源码分析）"
    return (
        f"解析文件 {diagnostics.parsed_file_count}/{diagnostics.total_source_files}，"
        f"调用 {diagnostics.total_calls} 个"
        f"（高置信度 {diagnostics.resolved_high}，"
        f"中置信度 {diagnostics.resolved_medium}，"
        f"未解析 {diagnostics.unresolved}）{cp_info}。"
    )


def _serialize_whitebox_result(
    result: WhiteboxResult,
    endpoint_count: int,
    finding_count: int,
    scope: str,
) -> dict:
    """将 WhiteboxResult 序列化为可 JSON 序列化的字典（供报告模板使用）。"""
    return {
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
