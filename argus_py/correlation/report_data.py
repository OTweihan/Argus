"""白盒报告关联数据构建（文件型报告 #correlation 区块）。

契约：本模块返回的 dict 只含 camelCase key。report_to_dict 末尾会递归执行
camel_keys_inplace，snake_case 键会被静默改名；因此任何新字段必须写 camelCase。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from argus_py.correlation.presenters import (
    correlation_run_to_dict,
    http_request_to_dict,
    summary_to_dict,
)

# correlation repo 批量查询单次上限 900，留安全余量
_CHUNK_SIZE = 800


def build_correlation_report_data(
    storage: Any,
    analysis_id: str,
) -> dict[str, Any] | None:
    """聚合绑定到该分析的所有关联运行，构建报告关联数据。

    无任何关联运行 → 返回 None（模板渲染空态，且不触发重生成）。
    跨运行语义：confirmedTouchedEndpointCount 为各运行确认触达端点的并集；
    unmatchedRequests 仅取最新运行的明细；findingRelations 按 finding 去重。
    明细列表均全量取数（无分页钳制），避免大型报告静默缺数据。
    """
    runs = storage.list_correlation_runs_by_analysis_ids([analysis_id])
    if not runs:
        return None

    run_dicts: list[dict[str, Any]] = []
    sums = _zero_correlation_sums()
    touched: dict[str, dict[str, Any]] = {}
    for run in runs:  # list_correlation_runs_by_analysis_ids 按 created_at DESC，首个即最新
        summary = storage.get_correlation_summary(run.correlation_run_id)
        sd = summary_to_dict(summary) if summary is not None else {}
        run_dicts.append({**correlation_run_to_dict(run), "summary": sd})
        _accumulate_correlation_sums(sums, sd)
        if not run.active_attempt_id:
            continue
        for g in storage.list_confirmed_touched_endpoints(run.active_attempt_id):
            item = touched.setdefault(
                g["endpoint_id"],
                {
                    "endpointId": g["endpoint_id"],
                    "httpMethod": g["http_method"],
                    "confirmedRequestCount": 0,
                    "evidenceIds": [],
                    "runIds": [],
                },
            )
            item["confirmedRequestCount"] += g["confirmed_request_count"]
            item["evidenceIds"].extend(e for e in str(g.get("evidence_ids") or "").split(",") if e)
            if run.correlation_run_id not in item["runIds"]:
                item["runIds"].append(run.correlation_run_id)

    ep_map = chunked_batch(storage.batch_get_endpoint_details, list(touched))
    for eid, item in touched.items():
        ep = ep_map.get(eid, {})
        item["path"] = ep.get("normalized_path_template") or ep.get("normalized_exact_path") or ""
        item["controllerClass"] = ep.get("controller_class")
        item["controllerMethod"] = ep.get("controller_method")
        item["returnType"] = ep.get("return_type")

    all_evidence_ids = [eid for item in touched.values() for eid in item["evidenceIds"]]
    # batch_get_flows 已把 endpoint_evidence_flows 快照行关联 analysis 侧执行流，
    # 返回完整 ExecutionFlowResponse 结构，直接消费即可（与端点证据 API 同源）。
    flows_map = chunked_batch(storage.batch_get_flows, all_evidence_ids)
    for item in touched.values():
        item["flows"] = _dedupe_flows(
            frow for eid in item["evidenceIds"] for frow in flows_map.get(eid, [])
        )
        item.pop("evidenceIds", None)

    # 未覆盖列表展示全量端点（按路径排序），避免被分页钳制为前 200 行导致
    # 列表与真实 total 计数不一致；端点集合已在匹配执行中全量加载过，
    # 此处为报告再取一次（仅被关联报告路径调用，频率低）。
    endpoints = storage.list_all_analysis_endpoints(analysis_id)
    total_endpoint_count = len(endpoints)
    touched_ids = set(touched)
    uncovered = [
        _endpoint_to_report_dict(ep) for ep in endpoints if ep.get("endpoint_id") not in touched_ids
    ]

    latest = runs[0]
    # 报告明细全量取数（无 limit 钳制）：与 aggregate.unmatchedRequestCount 保持
    # 一致，避免固定 limit 在大型运行中静默截断报告数据。
    unmatched_rows = storage.list_all_unmatched_requests(latest.correlation_run_id)
    unmatched = [http_request_to_dict(r) for r in unmatched_rows]

    finding_relations = _build_finding_relations(storage, runs)

    return {
        "analysisId": analysis_id,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "runs": run_dicts,
        "aggregate": {
            "runCount": len(runs),
            "latestCorrelationRunId": latest.correlation_run_id,
            "evidenceCompleteness": sums["evidenceCompleteness"],
            "capturedRequestCount": sums["capturedRequestCount"],
            "correlatableRequestCount": sums["correlatableRequestCount"],
            "confirmedMatchedRequestCount": sums["confirmedMatchedRequestCount"],
            "ambiguousRequestCount": sums["ambiguousRequestCount"],
            "unmatchedRequestCount": sums["unmatchedRequestCount"],
            "confirmedTouchedEndpointCount": len(touched),
            "uncoveredEndpointCount": max(0, total_endpoint_count - len(touched)),
            "totalEndpointCount": total_endpoint_count,
            "confirmedRelatedFindingCount": sums["confirmedRelatedFindingCount"],
            "candidateRelatedFindingCount": sums["candidateRelatedFindingCount"],
            "unrelatedFindingCount": sums["unrelatedFindingCount"],
        },
        "touchedEndpoints": list(touched.values()),
        "uncoveredEndpoints": uncovered,
        "unmatchedRequests": unmatched,
        "findingRelations": finding_relations,
    }


def _zero_correlation_sums() -> dict[str, Any]:
    return {
        "evidenceCompleteness": "COMPLETE",
        "capturedRequestCount": 0,
        "correlatableRequestCount": 0,
        "confirmedMatchedRequestCount": 0,
        "ambiguousRequestCount": 0,
        "unmatchedRequestCount": 0,
        "confirmedRelatedFindingCount": 0,
        "candidateRelatedFindingCount": 0,
        "unrelatedFindingCount": 0,
    }


def _accumulate_correlation_sums(sums: dict[str, Any], sd: dict[str, Any]) -> None:
    """累加单个运行的汇总计数（camelCase key 的 summary_to_dict 输出）。"""
    for key in (
        "capturedRequestCount",
        "correlatableRequestCount",
        "confirmedMatchedRequestCount",
        "ambiguousRequestCount",
        "unmatchedRequestCount",
        "confirmedRelatedFindingCount",
        "candidateRelatedFindingCount",
        "unrelatedFindingCount",
    ):
        value = sd.get(key)
        if isinstance(value, int):
            sums[key] = sums.get(key, 0) + value
    completeness = sd.get("evidenceCompleteness")
    if isinstance(completeness, str):
        sums["evidenceCompleteness"] = completeness  # 取最新运行


def chunked_batch(
    batch_fn: Callable[[list[str]], dict[str, Any]],
    ids: list[str],
    chunk_size: int = _CHUNK_SIZE,
) -> dict[str, Any]:
    """按批次大小分片调用批量查询（correlation repo 单次上限 900）。

    batch_fn 返回 {id: row} 映射，合并返回。
    """
    result: dict[str, Any] = {}
    for i in range(0, len(ids), chunk_size):
        result.update(batch_fn(ids[i : i + chunk_size]))
    return result


def _dedupe_flows(flows: Any) -> list[dict[str, Any]]:
    """按 execution_flow_id 去重。"""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for flow in flows:
        fid = flow.get("executionFlowId")
        if fid and fid not in seen:
            seen.add(fid)
            result.append(flow)
    return result


def _endpoint_to_report_dict(ep: dict[str, Any]) -> dict[str, Any]:
    """将 analysis_endpoints 行转为报告用 camelCase dict。"""
    return {
        "endpointId": ep.get("endpoint_id"),
        "httpMethod": ep.get("http_method"),
        "path": ep.get("normalized_path_template") or ep.get("normalized_exact_path") or "",
        "controllerClass": ep.get("controller_class"),
        "controllerMethod": ep.get("controller_method"),
        "returnType": ep.get("return_type"),
    }


def _build_finding_relations(
    storage: Any,
    runs: list[Any],
) -> list[dict[str, Any]]:
    """跨运行聚合 Finding 关联：按 finding_id 去重，保留最大确认请求数。"""
    merged: dict[str, dict[str, Any]] = {}
    for run in runs:
        # 全量取数（无 limit 钳制），避免超过 500 行时报告关联静默缺失。
        for row in storage.list_all_finding_evidence(run.correlation_run_id):
            fid = row.get("finding_id")
            if not fid:
                continue
            count = row.get("confirmed_request_count") or 0
            existing = merged.get(fid)
            if existing is not None and count <= existing.get("confirmedRequestCount", 0):
                continue
            merged[fid] = {
                "findingId": fid,
                "bestRelationType": row.get("best_relation_type") or "UNKNOWN",
                "confirmedRequestCount": count,
            }
    if not merged:
        return []
    details = chunked_batch(storage.batch_get_finding_details, list(merged))
    for fid, item in merged.items():
        d = details.get(fid, {})
        item["title"] = d.get("title") or ""
        item["severity"] = d.get("severity") or ""
        item["findingType"] = d.get("finding_type") or "unknown"
        item["ruleId"] = d.get("rule_id")
        item["ruleCategory"] = d.get("rule_category")
        item["location"] = d.get("location")
    return list(merged.values())
