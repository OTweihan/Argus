"""阶段三：匹配器执行辅助 — 采集质量评估、完整性决策、调用流与 Finding 证据生成。

供 container.py（异步路径）和 application.py（同步路径）共用，
避免 ~120 行重复的流/Finding 关联生成逻辑。
"""

from __future__ import annotations

import re as _re
import uuid as _uuid_mod
from typing import Any

from argus_py.correlation.enums import (
    EvidenceCompleteness,
    FindingRelationType,
    PartialReasonCode,
)
from argus_py.correlation.models import (
    CorrelationAttemptDiagnostic,
    CorrelationAttemptReason,
    EndpointEvidenceFlow,
    FindingEvidence,
    FindingEvidenceLink,
)

# 关联类型优先级：DIRECT_HANDLER > FLOW_MEMBER > STATIC_REACHABLE > UNKNOWN。
_FINDING_RELATION_PRIORITY: dict[FindingRelationType, int] = {
    FindingRelationType.DIRECT_HANDLER: 0,
    FindingRelationType.FLOW_MEMBER: 1,
    FindingRelationType.STATIC_REACHABLE: 2,
    FindingRelationType.UNKNOWN: 3,
}


def assess_capture_quality(cq: dict[str, Any] | None) -> tuple[bool, bool]:
    """从 CaptureQuality dict 提取截断和持久化失败标志。

    Returns:
        (capture_truncated, has_persistence_failure)
    """
    if cq is None:
        return False, False
    truncated = bool(cq.get("truncated", 0))
    failed = bool(cq.get("persistence_failed", 0))
    writer_failed = bool(cq.get("writer_failed_batch_count", 0))
    return truncated, failed or writer_failed


def build_quality_reasons(
    attempt_id: str,
    cq: dict[str, Any] | None,
    capture_truncated: bool,
    has_persistence_failure: bool,
) -> tuple[list[CorrelationAttemptReason], list[CorrelationAttemptDiagnostic]]:
    """根据采集质量构造 reasons 和 diagnostics 列表。

    调用方负责在无 eligible_requests 时追加 NO_ELIGIBLE_REQUESTS diagnostic。
    """
    reasons: list[CorrelationAttemptReason] = []
    diagnostics: list[CorrelationAttemptDiagnostic] = []

    if capture_truncated:
        reasons.append(
            CorrelationAttemptReason(
                correlation_attempt_id=attempt_id,
                reason_code=PartialReasonCode.CAPTURE_TRUNCATED,
                detail=cq.get("truncation_reason") if cq else "采集被截断",
            )
        )
    if has_persistence_failure:
        reasons.append(
            CorrelationAttemptReason(
                correlation_attempt_id=attempt_id,
                reason_code=PartialReasonCode.REQUEST_PERSISTENCE_FAILED,
                detail=(
                    f"持久化失败: {cq.get('persistence_failed', 0)} 条, "
                    f"writer 批次失败: {cq.get('writer_failed_batch_count', 0)}"
                    if cq
                    else "持久化失败"
                ),
            )
        )

    return reasons, diagnostics


def resolve_completeness(
    has_reasons: bool,
    capture_truncated: bool,
    has_persistence_failure: bool,
) -> EvidenceCompleteness:
    """根据质量标志确定 attempt 完整性结论。

    - 有截断或持久化失败 → PARTIAL
    - 否则 → COMPLETE
    """
    if has_reasons or capture_truncated or has_persistence_failure:
        return EvidenceCompleteness.PARTIAL
    return EvidenceCompleteness.COMPLETE


def execute_correlation(
    storage: Any,
    cr: Any,
    attempt: Any,
    *,
    on_completed: Any | None = None,
    path_mapping: Any | None = None,
) -> None:
    """关联匹配编排的单一实现 — 纯 CPU + 同步 SQLite 操作。

    这是 application.py（同步路径）与 container.py（异步路径）共享的编排层：
    两者此前各持一份约 150 行的近逐字副本，任何修复/新字段都需双处同步，
    现收敛为一处。流程：

    1. ``cr.analysis_id`` 为空 → 直接 FAILED/PARTIAL 落终态；
    2. 读采集质量、生成 reasons/diagnostics；
    3. 取合格请求做早退判断（无合格请求时无需加载投影全量行）；
    4. 全量加载端点/执行流/调用节点 → 匹配 → 写证据/候选；
    5. 生成调用流关联与 Finding 证据关联；
    6. 决定 completeness 并 ``complete_and_activate_attempt``。

    ``on_completed(analysis_id, correlation_run_id)`` 在 Attempt 落终态后调用。
    """
    from argus_py.correlation.enums import (
        AttemptDiagnosticCode,
        AttemptStatus,
    )
    from argus_py.correlation.matcher import EndpointMatcher

    if cr.analysis_id is None:
        storage.complete_and_activate_attempt(
            attempt.correlation_attempt_id,
            AttemptStatus.FAILED.value,
            EvidenceCompleteness.PARTIAL.value,
        )
        # 与原 _execute_matching_sync 语义一致：analysis_id 缺失属「未绑定分析」，
        # 直接落 FAILED 终态，不触发 on_completed 报告重生成（无 analysis_id 可关联）。
        return

    # ── 读取采集质量 ──
    cq = storage.get_capture_quality(cr.blackbox_run_id)
    capture_truncated, has_persistence_failure = assess_capture_quality(cq)
    reasons, diagnostics = build_quality_reasons(
        attempt.correlation_attempt_id,
        cq,
        capture_truncated,
        has_persistence_failure,
    )

    # 先取合格请求做早退判断：无合格请求时无需加载投影全量行（端点/执行流/
    # 调用节点），避免浪费三次大查询。
    eligible_requests = storage.list_eligible_requests(cr.blackbox_run_id)

    if not eligible_requests:
        diagnostics.append(
            CorrelationAttemptDiagnostic(
                correlation_attempt_id=attempt.correlation_attempt_id,
                diagnostic_code=AttemptDiagnosticCode.NO_ELIGIBLE_REQUESTS,
                detail=f"blackbox_run_id={cr.blackbox_run_id} 无 CONFIRMED_ELIGIBLE 请求",
            )
        )
        completeness = resolve_completeness(
            bool(reasons),
            capture_truncated,
            has_persistence_failure,
        )
        if reasons:
            storage.insert_attempt_reasons_batch(reasons)
        if diagnostics:
            storage.insert_attempt_diagnostics_batch(diagnostics)
        storage.complete_and_activate_attempt(
            attempt.correlation_attempt_id,
            (
                AttemptStatus.PARTIAL
                if completeness == EvidenceCompleteness.PARTIAL
                else AttemptStatus.SUCCEEDED
            ).value,
            completeness.value,
        )
        if on_completed is not None:
            on_completed(cr.analysis_id, cr.correlation_run_id)
        return

    # 关联匹配需要投影全量行（不做 200 行分页钳制）；执行流/调用节点一次取全，
    # 供 generate_flows / generate_finding_evidence 共用，避免同一分析内重复查询。
    endpoints = storage.list_all_analysis_endpoints(cr.analysis_id)
    analysis_flows = storage.list_all_analysis_execution_flows(cr.analysis_id)
    call_nodes = storage.list_all_analysis_call_nodes(cr.analysis_id)

    matcher = EndpointMatcher(
        matcher_version="v1",
        normalization_version="v1",
        path_mapping=path_mapping,
    )
    result = matcher.match_batch(eligible_requests, endpoints)

    # 诊断：正则约束不可移植
    if result.diagnostics:
        diagnostics.extend(
            CorrelationAttemptDiagnostic(
                correlation_attempt_id=attempt.correlation_attempt_id,
                diagnostic_code=d,
                detail=None,
            )
            for d in result.diagnostics
        )

    # 写入证据（填充 correlation_run_id 和 attempt_id）
    for ev in result.evidence_list:
        ev.correlation_run_id = cr.correlation_run_id
        ev.correlation_attempt_id = attempt.correlation_attempt_id

    storage.insert_endpoint_evidence_batch(result.evidence_list)
    if result.candidates:
        storage.insert_candidates_batch(result.candidates)

    # ── 生成调用流关联 ──
    flows = generate_flows(
        storage, cr.analysis_id, result.evidence_list, endpoints, flows=analysis_flows
    )
    if flows:
        storage.insert_flows_batch(flows)

    # ── 生成 Finding 证据关联 ──
    finding_evidence_list, finding_links = generate_finding_evidence(
        storage,
        cr.analysis_id,
        attempt.correlation_attempt_id,
        result.evidence_list,
        endpoints,
        flows=analysis_flows,
        call_nodes=call_nodes,
    )
    if finding_evidence_list:
        storage.insert_finding_evidence_batch(finding_evidence_list)
    if finding_links:
        storage.insert_finding_links_batch(finding_links)

    # ── 决定 completeness ──
    completeness = resolve_completeness(
        bool(reasons),
        capture_truncated,
        has_persistence_failure,
    )
    if reasons:
        storage.insert_attempt_reasons_batch(reasons)
    if diagnostics:
        storage.insert_attempt_diagnostics_batch(diagnostics)

    storage.complete_and_activate_attempt(
        attempt.correlation_attempt_id,
        (
            AttemptStatus.PARTIAL
            if completeness == EvidenceCompleteness.PARTIAL
            else AttemptStatus.SUCCEEDED
        ).value,
        completeness.value,
    )
    if on_completed is not None:
        on_completed(cr.analysis_id, cr.correlation_run_id)


# ── 调用流生成（异步/同步路径共用）────────────────────────────────


def _format_endpoint_location(endpoint: dict[str, Any]) -> str:
    """格式化端点源码位置为可读字符串。"""
    sf = endpoint.get("source_file") or ""
    sl = endpoint.get("source_start_line")
    parts = [sf]
    if sl is not None:
        parts.append(f":{sl}")
    return "".join(parts)


def _build_flow_indices(
    flows: list[dict[str, Any]],
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    """构建执行流双重索引（接收已取全的执行流列表）。

    Returns:
        (flows_by_entry, flows_by_method)
        - flows_by_entry: "ControllerClass.methodName" → [flow, ...]
        - flows_by_method: "methodName" → [flow, ...]
    """
    flows_by_entry: dict[str, list[dict[str, Any]]] = {}
    flows_by_method: dict[str, list[dict[str, Any]]] = {}
    for flow in flows:
        entry = flow.get("entry_point", "")
        if not entry:
            continue
        flows_by_entry.setdefault(entry, []).append(flow)
        # "UserController.listUsers" → "listUsers"
        dot_pos = entry.rfind(".")
        method_name = entry[dot_pos + 1 :] if dot_pos > 0 else entry
        flows_by_method.setdefault(method_name, []).append(flow)

    return flows_by_entry, flows_by_method


def generate_flows(
    storage: Any,
    analysis_id: str,
    evidence_list: list[Any],
    endpoints: list[dict[str, Any]],
    *,
    flows: list[dict[str, Any]] | None = None,
) -> list[Any]:
    """为已匹配的端点证据生成 EndpointEvidenceFlow 关联。

    查询分析执行中的 execution_flows，按 controller_method 匹配端点。
    建立 method_name → flows 索引以避免 O(n×m) 回退扫描。

    ``flows`` 为可选：调用方若已取全执行流（关联匹配单次取数），传入可避免
    同一分析内重复查询；未传入时内部经 ``list_all_analysis_execution_flows``
    取全（不做 200 行分页钳制）。
    """
    # 构建 endpoint_id → endpoint 映射
    ep_map: dict[str, dict[str, Any]] = {}
    for ep in endpoints:
        eid = ep.get("endpoint_id")
        if eid:
            ep_map[eid] = ep

    if flows is None:
        flows = storage.list_all_analysis_execution_flows(analysis_id)
    flows_by_entry, flows_by_method = _build_flow_indices(flows)

    result: list[Any] = []
    seen: set[tuple[str, str]] = set()

    for ev in evidence_list:
        ep_id = ev.matched_endpoint_id
        if not ep_id:
            continue

        endpoint = ep_map.get(ep_id)
        if endpoint is None:
            continue

        controller_method = endpoint.get("controller_method", "")
        controller_class = endpoint.get("controller_class", "")
        entry_key = f"{controller_class}.{controller_method}" if controller_class else ""

        # 查找：类.方法 → 纯方法名
        matching_flows = flows_by_entry.get(entry_key, []) if entry_key else []
        if not matching_flows:
            matching_flows = flows_by_method.get(controller_method, [])

        for flow in matching_flows:
            flow_id = flow.get("execution_flow_id", "")
            dedup_key = (ev.endpoint_evidence_id, flow_id)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            endpoint_path = endpoint.get("normalized_path_template") or endpoint.get(
                "normalized_exact_path", ""
            )
            result.append(
                EndpointEvidenceFlow(
                    endpoint_evidence_id=ev.endpoint_evidence_id,
                    execution_flow_id=flow_id,
                    relation_type="ENTRY_POINT",
                    endpoint_method_snapshot=endpoint.get("http_method"),
                    endpoint_path_snapshot=endpoint_path,
                    controller_snapshot=controller_method,
                    flow_name_snapshot=flow.get("entry_point"),
                    source_location_snapshot=_format_endpoint_location(endpoint),
                )
            )

    return result


# ── 位置解析与关系判定辅助 ──────────────────────────────────────

_LOCATION_RE = _re.compile(r"^(?P<file>.+?)(?::L?|#L?)(?P<start>\d+)(?:[-,](?P<end>\d+))?")


def _parse_finding_location(
    location: str | None,
) -> tuple[str, int, int | None]:
    """从 finding.location 解析出 (source_file, start_line, end_line)。

    标准化：反斜杠 → 正斜杠，end_line 为 None 时视为单行。
    """
    if not location:
        return "", 0, None
    normalized = location.replace("\\", "/")
    m = _LOCATION_RE.search(normalized)
    if m is None:
        return normalized, 0, None
    return (
        m.group("file").replace("\\", "/"),
        int(m.group("start")),
        int(m.group("end")) if m.group("end") else None,
    )


def _line_within_range(
    finding_start: int,
    finding_end: int | None,
    ep_start: int | None,
    ep_end: int | None,
) -> bool:
    """判断 finding 的行范围是否落在端点/方法源码范围内。"""
    if ep_start is None:
        return False
    f_end = finding_end if finding_end is not None else finding_start
    ep_finish = ep_end if ep_end is not None else ep_start
    return finding_start <= ep_finish and f_end >= ep_start


def _build_method_line_index(
    call_nodes: list[dict[str, Any]],
) -> dict[str, list[tuple[int, int | None, str]]]:
    """构建 (source_file) → [(start_line, end_line, method_key), ...] 索引。"""
    index: dict[str, list[tuple[int, int | None, str]]] = {}
    for cn in call_nodes:
        sf = (cn.get("source_file") or "").replace("\\", "/")
        if not sf:
            continue
        sl = cn.get("source_start_line")
        if not isinstance(sl, int):
            continue
        cn_class = cn.get("class_name") or ""
        cn_method = cn.get("method_name") or ""
        mk = f"{cn_class}.{cn_method}" if cn_class else cn_method
        if not mk:
            continue
        el = cn.get("source_end_line")
        index.setdefault(sf, []).append(
            (
                sl,
                int(el) if isinstance(el, int) else None,
                mk,
            )
        )
    return index


def _build_flow_method_index(
    call_nodes: list[dict[str, Any]],
    flow_steps: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """构建 flow_id → set of method_keys 索引。

    接收已取全的 call_nodes 与 flow_steps（关联匹配单次取数），避免重复查询。
    """
    # 构建 call_node_id → method_key 映射
    cn_method: dict[str, str] = {}
    for cn in call_nodes:
        cn_id = cn.get("call_node_id", "")
        cn_class = cn.get("class_name") or ""
        cn_method_name = cn.get("method_name") or ""
        if cn_id and cn_method_name:
            cn_method[cn_id] = f"{cn_class}.{cn_method_name}" if cn_class else cn_method_name

    # 按 execution_flow_id 分组
    flow_methods: dict[str, set[str]] = {}
    steps_by_flow: dict[str, list[dict[str, Any]]] = {}
    for step in flow_steps:
        flow_id = step.get("execution_flow_id", "")
        if flow_id:
            steps_by_flow.setdefault(flow_id, []).append(step)

    for flow_id, steps in steps_by_flow.items():
        method_keys: set[str] = set()
        for step in steps:
            mk = step.get("method_key") or ""
            if mk:
                method_keys.add(mk)
                continue
            cn_id = step.get("call_node_id") or ""
            fallback = cn_method.get(cn_id)
            if fallback:
                method_keys.add(fallback)
        if method_keys:
            flow_methods[flow_id] = method_keys

    return flow_methods


def _find_flows_for_endpoint(
    endpoint: dict[str, Any],
    flows_by_entry: dict[str, list[dict[str, Any]]],
    flows_by_method: dict[str, list[dict[str, Any]]],
) -> set[str]:
    """查找与给定端点关联的 flow_id 集合（与 generate_flows 相同匹配逻辑）。"""
    controller_method = endpoint.get("controller_method", "")
    controller_class = endpoint.get("controller_class", "")
    entry_key = f"{controller_class}.{controller_method}" if controller_class else ""
    flow_ids: set[str] = set()
    for f in flows_by_entry.get(entry_key, []):
        flow_ids.add(f.get("execution_flow_id", ""))
    for f in flows_by_method.get(controller_method, []):
        flow_ids.add(f.get("execution_flow_id", ""))
    flow_ids.discard("")
    return flow_ids


def _determine_relation_type(
    finding_file: str,
    finding_start: int,
    finding_end: int | None,
    endpoint: dict[str, Any],
    method_line_index: dict[str, list[tuple[int, int | None, str]]],
    flow_method_index: dict[str, set[str]],
    endpoint_flow_ids: set[str],
) -> FindingRelationType:
    """根据 finding 源码位置与端点的关系确定 FindingRelationType。

    判定优先级：
    1. DIRECT_HANDLER  — 同文件且行号落在端点源码范围内
    2. FLOW_MEMBER     — finding 的方法出现在端点的执行流中
    3. STATIC_REACHABLE — 同文件但行号不在端点范围内
    4. UNKNOWN         — 无法建立关联
    """
    ep_file = (endpoint.get("source_file") or "").replace("\\", "/")
    ep_file_name = ep_file.rsplit("/", 1)[-1] if ep_file else ""

    # 文件名匹配（纯文件名或全路径后缀）
    file_match = bool(finding_file) and (
        ep_file.endswith(finding_file) or finding_file.endswith(ep_file_name)
    )

    # 1. DIRECT_HANDLER
    if file_match and finding_start > 0:
        if _line_within_range(
            finding_start,
            finding_end,
            endpoint.get("source_start_line"),
            endpoint.get("source_end_line"),
        ):
            return FindingRelationType.DIRECT_HANDLER

    # 2. FLOW_MEMBER
    if endpoint_flow_ids and method_line_index and finding_file and finding_start > 0:
        methods_for_file = method_line_index.get(finding_file, [])
        for cn_start, cn_end, mk in methods_for_file:
            if _line_within_range(finding_start, finding_end, cn_start, cn_end):
                for flow_id in endpoint_flow_ids:
                    if mk in flow_method_index.get(flow_id, set()):
                        return FindingRelationType.FLOW_MEMBER
                break

    # 3. STATIC_REACHABLE
    if file_match:
        return FindingRelationType.STATIC_REACHABLE

    return FindingRelationType.UNKNOWN


def _add_endpoint(
    ep: dict[str, Any],
    rel: FindingRelationType,
    matched_eps: list[dict[str, Any]],
    seen_ep_ids: set[str],
    ep_relation: dict[str, FindingRelationType],
) -> None:
    """去重添加端点到匹配列表并记录其 relation_type。"""
    eid = ep.get("endpoint_id", "")
    if eid and eid not in seen_ep_ids:
        seen_ep_ids.add(eid)
        matched_eps.append(ep)
        ep_relation[eid] = rel


# ── Finding 证据生成（异步/同步路径共用）────────────────────────────


def generate_finding_evidence(
    storage: Any,
    analysis_id: str,
    correlation_attempt_id: str,
    evidence_list: list[Any],
    endpoints: list[dict[str, Any]],
    *,
    flows: list[dict[str, Any]] | None = None,
    call_nodes: list[dict[str, Any]] | None = None,
) -> tuple[list[Any], list[Any]]:
    """为分析中的发现项生成 FindingEvidence 和 FindingEvidenceLink。

    匹配策略（按优先级）：
    1. finding.location 源码行号落在 endpoint.source_start/end_line 内
       → DIRECT_HANDLER
    2. finding 所在方法出现在 endpoint 关联的执行流中
       → FLOW_MEMBER
    3. finding 与 endpoint 同一源文件但行号不在端点范围内
       → STATIC_REACHABLE
    4. finding.url 与 endpoint 路径匹配
       → DIRECT_HANDLER（URL 匹配视为 confirmed）
    5. 无匹配 → UNKNOWN

    ``flows``/``call_nodes`` 为可选：调用方若已取全（关联匹配单次取数）传入可避免
    同一分析内重复查询；未传入时内部经 ``list_all_*`` 取全（不做 200 行钳制）。
    """
    if flows is None:
        flows = storage.list_all_analysis_execution_flows(analysis_id)
    if call_nodes is None:
        call_nodes = storage.list_all_analysis_call_nodes(analysis_id)
    all_findings = storage.list_all_analysis_findings(analysis_id)
    if not all_findings:
        return [], []

    # ── 构建索引 ──
    # endpoint 按 source_file 索引
    ep_index_by_file: dict[str, list[dict[str, Any]]] = {}
    for ep in endpoints:
        sf = (ep.get("source_file") or "").replace("\\", "/")
        if sf:
            ep_index_by_file.setdefault(sf, []).append(ep)

    # evidence 按 matched_endpoint_id 索引（列表，保留全部请求证据）
    ev_list_by_ep_id: dict[str, list[Any]] = {}
    for ev in evidence_list:
        ep_id = ev.matched_endpoint_id
        if ep_id:
            ev_list_by_ep_id.setdefault(ep_id, []).append(ev)

    # 执行流索引（共享 _build_flow_indices，用于 FLOW_MEMBER 判定）
    flows_by_entry, flows_by_method = _build_flow_indices(flows)

    # 方法行号索引 + flow→methods 索引
    method_line_index = _build_method_line_index(call_nodes)
    flow_steps = storage.list_all_analysis_flow_steps(analysis_id)
    flow_method_index = _build_flow_method_index(call_nodes, flow_steps)

    fe_list: list[Any] = []
    fl_list: list[Any] = []

    for finding in all_findings:
        fid = getattr(finding, "finding_id", "")
        if not fid:
            continue

        fe_id = f"fe:{_uuid_mod.uuid4().hex[:12]}"
        finding_loc = (getattr(finding, "location", "") or "").replace("\\", "/")
        finding_url = getattr(finding, "url", "") or ""

        # 解析行号
        finding_file, finding_start, finding_end = _parse_finding_location(
            getattr(finding, "location", None)
        )
        finding_file_name = finding_file.rsplit("/", 1)[-1] if finding_file else ""

        matched_eps: list[dict[str, Any]] = []
        seen_ep_ids: set[str] = set()
        # 记录每个端点的 relation_type
        ep_relation: dict[str, FindingRelationType] = {}

        # Level 1: source_file 匹配（行号 → DIRECT_HANDLER/STATIC_REACHABLE）
        if finding_file_name:
            for sf, eps in ep_index_by_file.items():
                sf_file = sf.rsplit("/", 1)[-1]
                if sf_file and sf_file == finding_file_name:
                    for ep in eps:
                        ep_flow_ids = _find_flows_for_endpoint(ep, flows_by_entry, flows_by_method)
                        rel = _determine_relation_type(
                            finding_file,
                            finding_start,
                            finding_end,
                            ep,
                            method_line_index,
                            flow_method_index,
                            ep_flow_ids,
                        )
                        _add_endpoint(ep, rel, matched_eps, seen_ep_ids, ep_relation)

        # Level 2: URL 匹配（仅在没有文件级匹配时回退）
        if not matched_eps and finding_url:
            for ep in endpoints:
                ep_path = ep.get("raw_path") or ep.get("normalized_exact_path", "")
                if ep_path and ep_path in finding_url:
                    _add_endpoint(
                        ep,
                        FindingRelationType.DIRECT_HANDLER,
                        matched_eps,
                        seen_ep_ids,
                        ep_relation,
                    )

        # 确定 best_relation_type（取最高优先级）
        if matched_eps:
            best_rel = min(
                (ep_relation[ep.get("endpoint_id", "")] for ep in matched_eps),
                key=lambda r: _FINDING_RELATION_PRIORITY.get(r, 99),
            )
        else:
            best_rel = FindingRelationType.UNKNOWN

        # confirmed_request_count = 匹配端点数中各端点对应请求证据数的总和
        confirmed_count = sum(
            len(ev_list_by_ep_id.get(ep.get("endpoint_id", ""), [])) for ep in matched_eps
        )

        fe = FindingEvidence(
            finding_evidence_id=fe_id,
            correlation_attempt_id=correlation_attempt_id,
            finding_id=fid,
            best_relation_type=best_rel,
            minimum_call_distance=0 if matched_eps else None,
            confirmed_request_count=confirmed_count,
            candidate_request_count=len(matched_eps),
            finding_rule_id_snapshot=getattr(finding, "rule_id", None) or None,
            finding_location_snapshot=finding_loc or None,
        )
        fe_list.append(fe)

        # 创建 FindingEvidenceLink（每个已匹配端点-请求证据对一条）
        for ep in matched_eps:
            ep_id = ep.get("endpoint_id", "")
            ep_ev_list = ev_list_by_ep_id.get(ep_id, [])
            rel = ep_relation.get(ep_id, best_rel)
            for ev in ep_ev_list:
                fl = FindingEvidenceLink(
                    finding_evidence_id=fe_id,
                    correlation_attempt_id=correlation_attempt_id,
                    endpoint_evidence_id=ev.endpoint_evidence_id,
                    endpoint_id=ep_id,
                    relation_type=rel,
                    call_distance=0,
                )
                fl_list.append(fl)

    return fe_list, fl_list
