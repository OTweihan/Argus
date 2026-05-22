"""白盒分析数据模型，与 Java DTO 对齐。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
class CallGraphNode:
    """调用图节点。"""

    class_name: str
    method_name: str
    method_signature: str
    callees: list[str] = field(default_factory=list)


@dataclass
class CallGraph:
    """调用图，key 为 className#methodName。"""

    nodes: dict[str, CallGraphNode] = field(default_factory=dict)


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
class WhiteboxResult:
    """白盒分析结果。"""

    endpoints: list[Endpoint] = field(default_factory=list)
    call_graph: CallGraph = field(default_factory=CallGraph)
    findings: list[WhiteboxFinding] = field(default_factory=list)

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
            nodes[key] = CallGraphNode(
                class_name=node.get("className", ""),
                method_name=node.get("methodName", ""),
                method_signature=node.get("methodSignature", ""),
                callees=node.get("callees", []),
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

        return cls(endpoints=endpoints, call_graph=call_graph, findings=findings)
