"""泛型 from_dict 反序列化独立测试矩阵。

部分测试直接调用私有辅助函数 ``_from_camel_dict`` 以覆盖
边界情况（如 list/dict 内部递归、json_key 别名等），
这些是内部实现细节的单元测试 —— 若未来泛型基础设施
提取到公共模块，相关测试也应同步迁移。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# _from_camel_dict 是私有 API，此处导入用于边界情况测试
from argus_py.whitebox.models import (
    AnalyzerDiagnostics,
    CallEdge,
    CallGraph,
    CallGraphNode,
    Endpoint,
    WhiteboxJobEvent,
    WhiteboxJobStatus,
    WhiteboxResult,
    _from_camel_dict,
)


# --- 1. 基础标量 ---
def test_basic_scalar_mapping():
    e = Endpoint.from_dict(
        {
            "path": "/api/hello",
            "httpMethod": "GET",
            "controllerClass": "com.example.HelloController",
            "controllerMethod": "hello",
            "parameters": [],
            "returnType": "String",
        }
    )
    assert e.path == "/api/hello"
    assert e.http_method == "GET"
    assert e.controller_class == "com.example.HelloController"
    assert e.controller_method == "hello"
    assert e.return_type == "String"


# --- 2. list[str] 透传 ---
def test_list_scalar_transparent():
    e = Endpoint.from_dict(
        {
            "path": "/api",
            "httpMethod": "POST",
            "controllerClass": "C",
            "controllerMethod": "m",
            "parameters": ["id", "name"],
            "returnType": "void",
        }
    )
    assert e.parameters == ["id", "name"]


# --- 3. list[Dataclass] ---
def test_list_dataclass():
    node = CallGraphNode.from_dict(
        {
            "className": "com.example.X",
            "methodName": "foo",
            "methodSignature": "void foo()",
            "calleeDetails": [{"to": "com.example.Service", "methodName": "greet"}],
        }
    )
    assert len(node.callee_details) == 1
    assert isinstance(node.callee_details[0], CallEdge)
    assert node.callee_details[0].method_name == "greet"


# --- 4. list[Dataclass] | None 为 null ---
def test_optional_list_dataclass_null():
    status = WhiteboxJobStatus.from_dict(
        {
            "jobId": "j1",
            "status": "RUNNING",
            "stage": "s",
            "createdAt": "2026-01-01",
            "events": None,
        }
    )
    assert status.events == []


# --- 5. list[Dataclass] | None 有值 ---
def test_optional_list_dataclass_value():
    status = WhiteboxJobStatus.from_dict(
        {
            "jobId": "j1",
            "status": "RUNNING",
            "stage": "s",
            "createdAt": "2026-01-01",
            "events": [{"timestamp": "t1", "stage": "s1", "level": "INFO", "message": "ok"}],
        }
    )
    assert len(status.events) == 1
    assert isinstance(status.events[0], WhiteboxJobEvent)
    assert status.events[0].message == "ok"


# --- 6. dict[str, str] 透传 ---
def test_dict_scalar_transparent():
    ad = AnalyzerDiagnostics.from_dict({"moduleTypes": {"app": "application"}})
    assert ad.module_types == {"app": "application"}


# --- 7. null list → default_factory ---
def test_null_list_uses_default_factory():
    ad = AnalyzerDiagnostics.from_dict(
        {
            "failedFiles": None,
            "classpathWarnings": None,
            "classpathErrors": None,
        }
    )
    assert ad.failed_files == []
    assert ad.classpath_warnings == []
    assert ad.classpath_errors == []


# --- 8. Optional 有值 ---
def test_optional_scalar_value():
    ad = AnalyzerDiagnostics.from_dict({"classpathExitCode": 1})
    assert ad.classpath_exit_code == 1


# --- 9. Optional 为 null ---
def test_optional_scalar_null():
    ad = AnalyzerDiagnostics.from_dict({"classpathExitCode": None})
    assert ad.classpath_exit_code is None


# --- 10. Optional 缺失 ---
def test_optional_scalar_missing():
    ad = AnalyzerDiagnostics.from_dict({})
    assert ad.classpath_exit_code is None


# --- 11. 嵌套 dataclass ---
def test_nested_dataclass():
    r = WhiteboxResult.from_dict(
        {
            "endpoints": [],
            "callGraph": {},
            "findings": [],
            "diagnostics": {"totalSourceFiles": 5},
        }
    )
    assert r.diagnostics is not None
    assert isinstance(r.diagnostics, AnalyzerDiagnostics)
    assert r.diagnostics.total_source_files == 5


# --- 12. 嵌套 dataclass = null（可选） ---
def test_nested_dataclass_null_optional():
    r = WhiteboxResult.from_dict(
        {
            "endpoints": [],
            "callGraph": {},
            "findings": [],
            "diagnostics": None,
        }
    )
    assert r.diagnostics is None


# --- 13. 嵌套 dataclass = null（不可选，有默认值） ---
def test_nested_dataclass_null_non_optional():
    # WhiteboxResult.call_graph 是 CallGraph（不可空），默认 default_factory=CallGraph
    r = WhiteboxResult.from_dict(
        {
            "endpoints": [],
            "findings": [],
            "callGraph": None,
        }
    )
    # call_graph 收到 null → _handle_null_value(Bare Dataclass) → _MISSING → default_factory
    assert isinstance(r.call_graph, CallGraph)
    assert len(r.call_graph.nodes) == 0


# --- 14. 无默认值字段缺失 key → None 兜底 ---
def test_missing_required_field():
    @dataclass
    class RequiredFieldModel:
        name: str
        age: int
        optional: str = "default"

    result = _from_camel_dict(RequiredFieldModel, {})
    assert result.name is None
    assert result.age is None
    assert result.optional == "default"


# --- 15. CallGraph 自定义 from_dict ---
def test_callgraph_custom_from_dict():
    cg = CallGraph.from_dict(
        {
            "com.example.Controller#index": {
                "className": "com.example.Controller",
                "methodName": "index",
                "methodSignature": "String index()",
            }
        }
    )
    assert "com.example.Controller#index" in cg.nodes
    assert isinstance(cg.nodes["com.example.Controller#index"], CallGraphNode)
    assert cg.nodes["com.example.Controller#index"].class_name == "com.example.Controller"


# --- 16. json_key metadata 别名 ---
def test_json_key_alias():
    @dataclass
    class AliasModel:
        url: str = field(default="", metadata={"json_key": "URL"})

    result = _from_camel_dict(AliasModel, {"URL": "https://example.com"})
    assert result.url == "https://example.com"


# --- 17. list[Dataclass | None] 含 null 元素 ---


@dataclass
class _NullableEvent:
    name: str = ""

    @classmethod
    def from_dict(cls, data):
        return _from_camel_dict(cls, data)


@dataclass
class _NullableContainer:
    events: list[_NullableEvent | None] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        return _from_camel_dict(cls, data)


def test_list_dataclass_or_none_with_null_element():

    # null 元素
    c = _NullableContainer.from_dict({"events": [None]})
    assert len(c.events) == 1
    assert c.events[0] is None

    # 有值元素
    c2 = _NullableContainer.from_dict({"events": [{"name": "test"}]})
    assert len(c2.events) == 1
    assert isinstance(c2.events[0], _NullableEvent)
    assert c2.events[0].name == "test"


# --- 18. 空输入 → 全默认 ---
def test_empty_input_all_defaults():
    r = WhiteboxResult.from_dict({})
    assert len(r.endpoints) == 0
    assert len(r.call_graph.nodes) == 0
    assert len(r.findings) == 0
    assert len(r.execution_flows) == 0
    assert len(r.clusters) == 0
    assert r.diagnostics is None


# --- 19. CallGraphNode 无 calleeDetails（缺失 key） ---
def test_callgraph_node_missing_callee_details():
    node = CallGraphNode.from_dict(
        {
            "className": "com.example.X",
            "methodName": "foo",
            "methodSignature": "void foo()",
        }
    )
    assert node.callee_details == []
