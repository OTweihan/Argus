"""白盒分析数据模型，与 Java DTO 对齐。"""

from __future__ import annotations

import types
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from functools import lru_cache
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

from argus_py.utils.casing import to_camel

# === 泛型 from_dict 基础设施 ===

_T = TypeVar("_T")


class _MissingType:
    """独立 sentinel，区分"key 不存在"和"key 存在但值为 None"。"""

    def __repr__(self) -> str:
        return "<MISSING>"


_MISSING = _MissingType()


@lru_cache(maxsize=None)
def _get_type_hints_cached(cls: type) -> dict[str, Any]:
    """缓存 get_type_hints 结果，避免每次 from_dict 重复解析。"""
    try:
        return get_type_hints(cls)
    except NameError as e:
        raise TypeError(f"Cannot resolve type annotations for {cls.__name__}: {e}") from e


def _is_dataclass_type(ftype: Any) -> bool:
    """判断类型是否为 dataclass（用 is_dataclass，不依赖 hasattr(from_dict)）。"""
    return isinstance(ftype, type) and is_dataclass(ftype)


def _handle_null_value(ftype: Any) -> Any:
    """处理 Java JSON 中字段值为 null 的情况。

    检查顺序至关重要：Union 必须先于 list/dict 检查，
    否则 ``list[str] | None`` 收到 null 时会被误判为集合空值。
    """
    origin = get_origin(ftype)
    args = get_args(ftype)

    # 1. Optional / Union — 例如 list[str] | None 收到 null 应返回 None
    if origin in (Union, types.UnionType):
        if type(None) in args:
            return None

    # 2. 集合类型 null → _MISSING → 走 default_factory
    if origin in (list, dict):
        return _MISSING

    # 3. 裸 dataclass / 标量 null → _MISSING
    return _MISSING


def _convert_value(raw: Any, ftype: Any) -> Any:
    """根据类型注解递归转换值（含 null 元素）。

    关键原则：Union 只负责拆包，真正类型转换递归走自身。
    入口处的 None 前置检查用于处理 list/dict 内部元素为 null 的情况
    （如 ``list[Dataclass | None]`` 含 null 元素）。
    """
    # 处理 list/dict 内部可能出现的 null 元素
    if raw is None:
        return _handle_null_value(ftype)

    origin = get_origin(ftype)
    args = get_args(ftype)

    # --- Union 拆包（不可提前终止，必须递归） ---
    if origin in (Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _convert_value(raw, non_none[0])  # 递归！
        return raw  # 多非 None 分支（极少），保守透传

    # --- list ---
    if origin is list:
        inner = args[0] if args else None
        if inner is not None:
            return [_convert_value(item, inner) for item in raw]
        return raw

    # --- dict ---
    if origin is dict:
        value_type = args[1] if len(args) >= 2 else None
        if value_type is not None:
            return {k: _convert_value(v, value_type) for k, v in raw.items()}
        return raw

    # --- 裸 dataclass ---
    if _is_dataclass_type(ftype):
        return ftype.from_dict(raw)

    # --- 标量 (int, str, bool, float) ---
    return raw


def _from_camel_dict(cls: type[Any], data: dict[str, Any]) -> Any:
    """从 camelCase JSON dict 泛型反序列化为 dataclass 实例。

    对每个字段：
    1. 通过 metadata["json_key"] 或 to_camel(field_name) 确定 JSON key
    2. key 缺失 → 有默认值用默认值，无默认值传 None 兜底
    3. 值为 null → 通过 _handle_null_value 分发
    4. 值非 null → 通过 _convert_value 递归转换
    """
    hints = _get_type_hints_cached(cls)  # type: ignore[arg-type]  # lru_cache wrapper type-stub issue
    kwargs: dict[str, Any] = {}

    for fd in fields(cls):
        # json_key 扩展点：优先 metadata，fallback to_camel
        json_key: str = fd.metadata.get("json_key", to_camel(fd.name))
        raw = data.get(json_key, _MISSING)

        if raw is _MISSING:
            # JSON 中没有此 key
            if fd.default is not MISSING or fd.default_factory is not MISSING:
                continue  # 有默认值 → 用默认值
            kwargs[fd.name] = None  # 无默认值 → None 兜底
            continue

        if raw is None:
            converted = _handle_null_value(hints.get(fd.name, fd.type))
        else:
            converted = _convert_value(raw, hints.get(fd.name, fd.type))

        if converted is not _MISSING:
            kwargs[fd.name] = converted

    return cls(**kwargs)


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
        return _from_camel_dict(cls, data)


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
        return _from_camel_dict(cls, data)


@dataclass
class CallGraphNode:
    """调用图节点。"""

    class_name: str
    method_name: str
    method_signature: str
    callee_details: list[CallEdge] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CallGraphNode:
        return _from_camel_dict(cls, data)


@dataclass
class CallGraph:
    """调用图，key 为 className#methodName。"""

    nodes: dict[str, CallGraphNode] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CallGraph:
        if not isinstance(data, dict):
            return cls()
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
        return _from_camel_dict(cls, data)


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
        return _from_camel_dict(cls, data)


@dataclass
class WhiteboxJobEvent:
    """Java 分析作业进度事件。"""

    timestamp: str = ""
    stage: str = ""
    level: str = ""
    message: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WhiteboxJobEvent:
        return _from_camel_dict(cls, data)


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
        return _from_camel_dict(cls, data)


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
        return _from_camel_dict(cls, data)


@dataclass
class FlowStep:
    """执行流中的一步。"""

    depth: int = 0
    method_key: str = ""
    class_name: str = ""
    method_name: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowStep:
        return _from_camel_dict(cls, data)


@dataclass
class ExecutionFlow:
    """从端点入口开始的完整调用链。"""

    entry_point: str = ""
    steps: list[FlowStep] = field(default_factory=list)
    call_depth: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionFlow:
        return _from_camel_dict(cls, data)


@dataclass
class ClusterInfo:
    """功能聚类分组。"""

    cluster_id: str = ""
    suggested_label: str = ""
    member_keys: list[str] = field(default_factory=list)
    member_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClusterInfo:
        return _from_camel_dict(cls, data)


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
        return _from_camel_dict(cls, data)
