"""SQLite 行 ↔ 领域模型双向映射。"""

from __future__ import annotations

import json
from typing import Any

from argus_py.core.constants import utc_now
from argus_py.core.enums import FindingSeverity, FindingType, StepResult, TaskStatus, TaskType
from argus_py.task.models import Finding, Task, TaskLog

# list_task_summaries 所需的 task 列（排除 whitebox_config_json / result_json 等大字段）
_TASK_SUMMARY_COLUMNS = (
    "task_id",
    "goal",
    "name",
    "start_url",
    "task_type",
    "status",
    "project_id",
    "max_steps",
    "timeout_seconds",
    "capture_screenshots",
    "current_step",
    "created_at",
    "started_at",
    "completed_at",
    "report_path",
    "result_summary",
    "error_message",
    "execution_attempt",
)


def task_summary_columns() -> str:
    """返回 list_task_summaries 查询用的列名列表。"""
    return ", ".join(_TASK_SUMMARY_COLUMNS)


def task_to_row(task: Task) -> tuple[Any, ...]:
    """将 Task 实体转换为 SQLite INSERT 参数。"""
    return (
        task.task_id,
        task.goal,
        task.name,
        task.start_url,
        task.task_type.value,
        task.status.value,
        task.project_id,
        task.max_steps,
        task.timeout_seconds,
        1 if task.capture_screenshots else 0,
        task.current_step,
        json.dumps(task.parameters, ensure_ascii=False),
        task.created_at.isoformat(),
        task.started_at.isoformat() if task.started_at else None,
        task.completed_at.isoformat() if task.completed_at else None,
        task.report_path,
        task.result_summary,
        task.error_message,
        task.whitebox_config_json,
        task.whitebox_config_schema_version,
        task.result_json,
        task.result_schema_version,
        task.result_size_bytes,
        task.source_type,
        task.source_repo_url,
        task.source_requested_ref,
        task.source_resolved_commit_sha,
        task.source_ref_type,
        1 if task.source_dirty else 0 if task.source_dirty is not None else None,
        task.external_job_id,
        task.external_job_status,
        task.external_job_submitted_at,
        task.external_job_last_polled_at,
        task.worker_id,
        task.worker_lease_expires_at,
        task.execution_attempt,
        task.retry_parent_task_id,
    )


def log_to_row(task_id: str, log: TaskLog) -> tuple[Any, ...]:
    """将 TaskLog 实体转换为 SQLite INSERT 参数。"""
    return (
        log.task_log_id,
        task_id,
        log.step_number,
        log.action,
        log.result.value,
        json.dumps(log.params, ensure_ascii=False),
        log.url_before,
        log.url_after,
        log.screenshot_path,
        log.message,
        log.error,
        log.error_code,
        log.created_at.isoformat(),
    )


def finding_to_row(task_id: str, finding: Finding) -> tuple[Any, ...]:
    """将 Finding 实体转换为 SQLite INSERT 参数。"""
    return (
        finding.finding_id,
        task_id,
        finding.title,
        finding.description,
        finding.severity.value,
        finding.finding_type.value,
        finding.url,
        finding.location,
        finding.screenshot_path,
        finding.created_at.isoformat(),
        finding.rule_id,
        finding.rule_category,
        finding.confidence,
        finding.fingerprint,
        finding.snippet,
        finding.analysis_id,
    )


def row_to_event(row: Any) -> Any:
    """将 SQLite 行还原为 TimelineEvent。"""
    from argus_py.task.event import TimelineEvent as TE
    from argus_py.task.models import _parse_datetime

    return TE(
        event_id=row["event_id"],
        task_id=row["task_id"],
        event_type=row["event_type"],
        phase=row["phase"],
        step_number=row["step_number"],
        summary=row["summary"],
        data=json.loads(row["data_json"] or "{}"),
        created_at=_parse_datetime(row["created_at"]) or utc_now(),
    )


def row_to_task(
    task_row: Any,
    log_rows: list[Any],
    finding_rows: list[Any],
) -> Task:
    """将 SQLite 行还原为 Task 实体。"""
    from argus_py.task.models import _parse_datetime

    return Task(
        task_id=task_row["task_id"],
        goal=task_row["goal"],
        name=task_row["name"],
        start_url=task_row["start_url"],
        task_type=TaskType(task_row["task_type"]),
        status=TaskStatus(task_row["status"]),
        project_id=task_row["project_id"],
        max_steps=task_row["max_steps"],
        timeout_seconds=task_row["timeout_seconds"],
        capture_screenshots=bool(task_row["capture_screenshots"]),
        parameters=json.loads(task_row["parameters_json"] or "{}"),
        logs=[row_to_log(r) for r in log_rows],
        findings=[row_to_finding(r) for r in finding_rows],
        created_at=_parse_datetime(task_row["created_at"]) or utc_now(),
        started_at=_parse_datetime(task_row["started_at"]),
        completed_at=_parse_datetime(task_row["completed_at"]),
        report_path=task_row["report_path"],
        result_summary=task_row["result_summary"],
        error_message=task_row["error_message"],
        whitebox_config_json=task_row["whitebox_config_json"],
        whitebox_config_schema_version=task_row["whitebox_config_schema_version"],
        result_json=task_row["result_json"],
        result_schema_version=task_row["result_schema_version"],
        result_size_bytes=task_row["result_size_bytes"],
        source_type=task_row["source_type"],
        source_repo_url=task_row["source_repo_url"],
        source_requested_ref=task_row["source_requested_ref"],
        source_resolved_commit_sha=task_row["source_resolved_commit_sha"],
        source_ref_type=task_row["source_ref_type"],
        source_dirty=(
            bool(task_row["source_dirty"]) if task_row["source_dirty"] is not None else None
        ),
        external_job_id=task_row["external_job_id"],
        external_job_status=task_row["external_job_status"],
        external_job_submitted_at=task_row["external_job_submitted_at"],
        external_job_last_polled_at=task_row["external_job_last_polled_at"],
        worker_id=task_row["worker_id"],
        worker_lease_expires_at=task_row["worker_lease_expires_at"],
        execution_attempt=task_row["execution_attempt"],
        retry_parent_task_id=task_row["retry_parent_task_id"],
    )


def row_to_log(row: Any) -> TaskLog:
    """将 SQLite 行还原为 TaskLog 实体。"""
    from argus_py.task.models import _parse_datetime

    return TaskLog(
        task_log_id=row["task_log_id"],
        step_number=row["step_number"],
        action=row["action"],
        result=StepResult(row["result"]),
        params=json.loads(row["params_json"] or "{}"),
        url_before=row["url_before"],
        url_after=row["url_after"],
        screenshot_path=row["screenshot_path"],
        message=row["message"],
        error=row["error"],
        error_code=row["error_code"],
        created_at=_parse_datetime(row["created_at"]) or utc_now(),
    )


def row_to_task_summary(task_row: Any) -> Task:
    """从摘要列集还原轻量 Task（不含日志/发现项/参数）。"""
    from argus_py.task.models import _parse_datetime

    return Task(
        task_id=task_row["task_id"],
        goal=task_row["goal"],
        name=task_row["name"],
        start_url=task_row["start_url"],
        task_type=TaskType(task_row["task_type"]),
        status=TaskStatus(task_row["status"]),
        project_id=task_row["project_id"],
        max_steps=task_row["max_steps"],
        timeout_seconds=task_row["timeout_seconds"],
        capture_screenshots=bool(task_row["capture_screenshots"]),
        parameters={},
        logs=[],
        findings=[],
        created_at=_parse_datetime(task_row["created_at"]) or utc_now(),
        started_at=_parse_datetime(task_row["started_at"]),
        completed_at=_parse_datetime(task_row["completed_at"]),
        report_path=task_row["report_path"],
        result_summary=task_row["result_summary"],
        error_message=task_row["error_message"],
        execution_attempt=task_row["execution_attempt"],
    )


def row_to_finding(row: Any) -> Finding:
    """将 SQLite 行还原为 Finding 实体。"""
    from argus_py.task.models import _parse_datetime

    return Finding(
        finding_id=row["finding_id"],
        title=row["title"],
        description=row["description"],
        severity=FindingSeverity(row["severity"]),
        finding_type=FindingType(row["finding_type"]),
        url=row["url"],
        location=row["location"],
        screenshot_path=row["screenshot_path"],
        created_at=_parse_datetime(row["created_at"]) or utc_now(),
        rule_id=row["rule_id"],
        rule_category=row["rule_category"],
        confidence=row["confidence"],
        fingerprint=row["fingerprint"],
        snippet=row["snippet"],
        analysis_id=row["analysis_id"],
    )


# ── 关联（correlation）行映射 ──────────────────────────────────────


def blackbox_run_to_row(run: Any) -> tuple:
    """将 BlackboxRun 实体转换为 SQLite INSERT 参数。"""
    return (
        run.blackbox_run_id,
        run.task_id,
        run.attempt,
        run.status.value,
        run.started_at,
        run.completed_at,
    )


def row_to_blackbox_run(row: dict[str, Any]) -> Any:
    """将 SQLite 行还原为 BlackboxRun 实体。"""
    from argus_py.correlation.enums import BlackboxRunStatus
    from argus_py.correlation.models import BlackboxRun

    return BlackboxRun(
        blackbox_run_id=row["blackbox_run_id"],
        task_id=row["task_id"],
        attempt=row["attempt"],
        status=BlackboxRunStatus(row["status"]),
        started_at=row["started_at"],
        completed_at=row.get("completed_at"),
    )


def correlation_run_to_row(run: Any) -> tuple:
    """将 CorrelationRun 实体转换为 SQLite INSERT 参数。"""
    from argus_py.core.constants import utc_now_iso

    return (
        run.correlation_run_id,
        run.project_id,
        run.blackbox_run_id,
        run.desired_source_snapshot_id,
        run.desired_analysis_config_digest,
        run.required_analyzer_version,
        int(run.allow_partial_analysis),
        run.analysis_id,
        run.bound_source_snapshot_id,
        run.analysis_projection_version,
        run.correlation_config_digest,
        run.matcher_version,
        run.normalization_version,
        run.supersedes_correlation_run_id,
        run.source_alignment_status.value,
        run.status.value,
        run.active_attempt_id,
        int(run.source_mismatch_overridden),
        run.source_mismatch_override_by,
        run.source_mismatch_override_at,
        run.source_mismatch_override_reason,
        run.started_at,
        run.completed_at,
        run.error_code,
        run.error_message,
        run.created_at or utc_now_iso(),
    )


def row_to_correlation_run(row: dict[str, Any]) -> Any:
    """将 SQLite 行还原为 CorrelationRun 实体。"""
    from argus_py.correlation.enums import CorrelationRunStatus, SourceAlignmentStatus
    from argus_py.correlation.models import CorrelationRun

    return CorrelationRun(
        correlation_run_id=row["correlation_run_id"],
        project_id=row["project_id"],
        blackbox_run_id=row["blackbox_run_id"],
        desired_source_snapshot_id=row["desired_source_snapshot_id"],
        desired_analysis_config_digest=row.get("desired_analysis_config_digest", ""),
        required_analyzer_version=row.get("required_analyzer_version", ""),
        allow_partial_analysis=bool(row.get("allow_partial_analysis", 0)),
        analysis_id=row.get("analysis_id"),
        bound_source_snapshot_id=row.get("bound_source_snapshot_id"),
        analysis_projection_version=row.get("analysis_projection_version"),
        correlation_config_digest=row.get("correlation_config_digest", ""),
        matcher_version=row.get("matcher_version", "v1"),
        normalization_version=row.get("normalization_version", "v1"),
        supersedes_correlation_run_id=row.get("supersedes_correlation_run_id"),
        source_alignment_status=SourceAlignmentStatus(
            row.get("source_alignment_status", "UNVERIFIED")
        ),
        status=CorrelationRunStatus(row.get("status", "WAITING_ANALYSIS")),
        active_attempt_id=row.get("active_attempt_id"),
        source_mismatch_overridden=bool(row.get("source_mismatch_overridden", 0)),
        source_mismatch_override_by=row.get("source_mismatch_override_by"),
        source_mismatch_override_at=row.get("source_mismatch_override_at"),
        source_mismatch_override_reason=row.get("source_mismatch_override_reason"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        created_at=row.get("created_at", ""),
    )


def attempt_to_row(attempt: Any) -> tuple:
    """将 CorrelationAttempt 实体转换为 SQLite INSERT 参数。"""
    from argus_py.core.constants import utc_now_iso

    return (
        attempt.correlation_attempt_id,
        attempt.correlation_run_id,
        attempt.attempt_number,
        attempt.analysis_id,
        attempt.source_snapshot_id,
        attempt.analysis_projection_version,
        attempt.matcher_version,
        attempt.normalization_version,
        attempt.correlation_config_digest,
        attempt.status.value,
        attempt.evidence_completeness.value,
        attempt.lease_owner,
        attempt.heartbeat_at,
        attempt.lease_expires_at,
        attempt.started_at,
        attempt.completed_at,
        attempt.error_code,
        attempt.error_message,
        attempt.created_at or utc_now_iso(),
    )


def row_to_attempt(row: dict[str, Any]) -> Any:
    """将 SQLite 行还原为 CorrelationAttempt 实体。"""
    from argus_py.correlation.enums import AttemptStatus, EvidenceCompleteness
    from argus_py.correlation.models import CorrelationAttempt

    return CorrelationAttempt(
        correlation_attempt_id=row["correlation_attempt_id"],
        correlation_run_id=row["correlation_run_id"],
        attempt_number=row["attempt_number"],
        analysis_id=row["analysis_id"],
        source_snapshot_id=row["source_snapshot_id"],
        analysis_projection_version=row["analysis_projection_version"],
        matcher_version=row.get("matcher_version", "v1"),
        normalization_version=row.get("normalization_version", "v1"),
        correlation_config_digest=row.get("correlation_config_digest", ""),
        status=AttemptStatus(row.get("status", "RUNNING")),
        evidence_completeness=EvidenceCompleteness(row.get("evidence_completeness", "COMPLETE")),
        lease_owner=row.get("lease_owner"),
        heartbeat_at=row.get("heartbeat_at"),
        lease_expires_at=row.get("lease_expires_at"),
        started_at=row.get("started_at", ""),
        completed_at=row.get("completed_at"),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        created_at=row.get("created_at", ""),
    )


def http_request_to_row(req: Any) -> tuple:
    """将 HttpRequestEvidence 实体转换为 SQLite INSERT 参数。"""
    return (
        req.request_evidence_id,
        req.blackbox_run_id,
        req.task_id,
        req.step_execution_id,
        req.step_attempt,
        req.request_sequence,
        req.http_method,
        req.normalized_path,
        req.display_path,
        req.origin,
        req.resource_type,
        req.endpoint_match_eligibility.value,
        req.response_status,
        req.outcome.value,
        req.failure_code,
        req.request_owner.value,
        int(req.response_from_service_worker),
        req.page_sequence,
        req.captured_at,
        req.finished_at,
    )


def row_to_http_request(row: dict[str, Any]) -> Any:
    """将 SQLite 行还原为 HttpRequestEvidence 实体。"""
    from argus_py.correlation.enums import (
        CorrelationEligibility,
        RequestOutcome,
        RequestOwner,
    )
    from argus_py.correlation.models import HttpRequestEvidence

    return HttpRequestEvidence(
        request_evidence_id=row["request_evidence_id"],
        blackbox_run_id=row["blackbox_run_id"],
        task_id=row["task_id"],
        step_execution_id=row.get("step_execution_id"),
        step_attempt=row.get("step_attempt", 1),
        request_sequence=row["request_sequence"],
        http_method=row["http_method"],
        normalized_path=row["normalized_path"],
        display_path=row["display_path"],
        origin=row["origin"],
        resource_type=row.get("resource_type", "other"),
        endpoint_match_eligibility=CorrelationEligibility(
            row.get("endpoint_match_eligibility", "CONFIRMED_ELIGIBLE")
        ),
        response_status=row.get("response_status"),
        outcome=RequestOutcome(row.get("outcome", "COMPLETED")),
        failure_code=row.get("failure_code"),
        request_owner=RequestOwner(row.get("request_owner", "FRAME")),
        response_from_service_worker=bool(row.get("response_from_service_worker", 0)),
        page_sequence=row.get("page_sequence", 0),
        captured_at=row["captured_at"],
        finished_at=row.get("finished_at"),
    )


def endpoint_evidence_to_row(ee: Any) -> tuple:
    """将 EndpointEvidence 实体转换为 SQLite INSERT 参数。"""
    from argus_py.core.constants import utc_now_iso

    return (
        ee.endpoint_evidence_id,
        ee.correlation_run_id,
        ee.correlation_attempt_id,
        ee.request_evidence_id,
        ee.resolution_status.value,
        ee.match_strategy.value,
        ee.confidence.value,
        ee.matched_endpoint_id,
        ee.matcher_version,
        ee.normalization_version,
        ee.candidate_count,
        ee.created_at or utc_now_iso(),
    )


# ── 分析执行与结构化投影行映射 ──────────────────────────────────────


def analysis_run_to_row(run: Any) -> tuple:
    """将 AnalysisRun 实体转换为 SQLite INSERT 参数。"""
    return (
        run.analysis_id,
        run.task_id,
        run.source_snapshot_id,
        run.resolved_commit_sha,
        run.run_status,
        run.completeness_status,
        run.external_job_id,
        run.external_job_status,
        run.failure_code,
        run.failure_message,
        run.stop_reason,
        run.result_schema_version,
        run.result_digest,
        run.config_json,
        run.raw_result_json,
        run.quality_policy_version,
        json.dumps([qi.to_dict() for qi in run.quality_issues], ensure_ascii=False),
        run.started_at,
        run.completed_at,
        run.projection_completed_at,
        run.created_at or utc_now().isoformat(),
        run.updated_at or utc_now().isoformat(),
    )


def row_to_analysis_run(row: Any) -> Any:
    """将 SQLite 行还原为 AnalysisRun 实体。"""
    from argus_py.analysis.models import AnalysisRun, QualityIssue

    # sqlite3.Row 没有 .get()，统一转 dict 后再读取
    if not isinstance(row, dict):
        row = dict(row)
    quality_issues_raw = row.get("quality_issues_json") or "[]"
    quality_issues = [QualityIssue.from_dict(qi) for qi in json.loads(quality_issues_raw)]
    return AnalysisRun(
        analysis_id=row["analysis_id"],
        task_id=row["task_id"],
        source_snapshot_id=row["source_snapshot_id"],
        resolved_commit_sha=row.get("resolved_commit_sha"),
        run_status=row["run_status"],
        completeness_status=row["completeness_status"],
        external_job_id=row.get("external_job_id"),
        external_job_status=row.get("external_job_status"),
        failure_code=row.get("failure_code"),
        failure_message=row.get("failure_message"),
        stop_reason=row.get("stop_reason"),
        result_schema_version=row.get("result_schema_version", 1),
        result_digest=row.get("result_digest"),
        config_json=row.get("config_json"),
        raw_result_json=row.get("raw_result_json"),
        quality_policy_version=row.get("quality_policy_version", 1),
        quality_issues=quality_issues,
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        projection_completed_at=row.get("projection_completed_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def endpoint_to_row(aid: str, ep: dict[str, Any]) -> tuple:
    """将 analysis_endpoints 投影行转为 SQLite 参数。"""
    return (
        ep["endpoint_id"],
        aid,
        ep["endpoint_fingerprint"],
        ep["http_method"],
        ep["raw_path"],
        ep.get("normalized_exact_path"),
        ep["normalized_path_template"],
        int(ep.get("is_templated", False)),
        ep.get("path_normalization_version", 1),
        ep.get("path_segment_count", 0),
        ep.get("static_prefix"),
        ep.get("canonical_path_shape"),
        ep.get("controller_class"),
        ep.get("controller_method"),
        ep.get("controller_method_signature"),
        json.dumps(ep.get("parameters", []), ensure_ascii=False),
        ep.get("return_type"),
        ep.get("source_file"),
        ep.get("source_start_line"),
        ep.get("source_start_column"),
        ep.get("source_end_line"),
        ep.get("source_end_column"),
        ep.get("entry_call_node_id"),
    )


def row_to_endpoint(row: dict[str, Any]) -> dict[str, Any]:
    """将 analysis_endpoints 行转为投影 dict。"""
    return {
        "endpoint_id": row["endpoint_id"],
        "endpoint_fingerprint": row["endpoint_fingerprint"],
        "http_method": row["http_method"],
        "raw_path": row["raw_path"],
        "normalized_exact_path": row.get("normalized_exact_path"),
        "normalized_path_template": row["normalized_path_template"],
        "is_templated": bool(row.get("is_templated", False)),
        "path_normalization_version": row.get("path_normalization_version", 1),
        "path_segment_count": row.get("path_segment_count", 0),
        "static_prefix": row.get("static_prefix"),
        "canonical_path_shape": row.get("canonical_path_shape"),
        "controller_class": row.get("controller_class"),
        "controller_method": row.get("controller_method"),
        "controller_method_signature": row.get("controller_method_signature"),
        "parameters": json.loads(row.get("parameters") or "[]"),
        "return_type": row.get("return_type"),
        "source_file": row.get("source_file"),
        "source_start_line": row.get("source_start_line"),
        "source_start_column": row.get("source_start_column"),
        "source_end_line": row.get("source_end_line"),
        "source_end_column": row.get("source_end_column"),
        "entry_call_node_id": row.get("entry_call_node_id"),
    }


def call_node_to_row(aid: str, cn: dict[str, Any]) -> tuple:
    """将 analysis_call_nodes 投影行转为 SQLite 参数。"""
    return (
        cn["call_node_id"],
        aid,
        cn["call_node_fingerprint"],
        cn["class_name"],
        cn["method_name"],
        cn.get("method_signature"),
        cn.get("source_file"),
        cn.get("source_start_line"),
        cn.get("source_start_column"),
        cn.get("source_end_line"),
        cn.get("source_end_column"),
    )


def row_to_call_node(row: dict[str, Any]) -> dict[str, Any]:
    """将 analysis_call_nodes 行转为投影 dict。"""
    return {
        "call_node_id": row["call_node_id"],
        "call_node_fingerprint": row["call_node_fingerprint"],
        "class_name": row["class_name"],
        "method_name": row["method_name"],
        "method_signature": row.get("method_signature"),
        "source_file": row.get("source_file"),
        "source_start_line": row.get("source_start_line"),
        "source_start_column": row.get("source_start_column"),
        "source_end_line": row.get("source_end_line"),
        "source_end_column": row.get("source_end_column"),
    }


def call_edge_to_row(aid: str, ce: dict[str, Any]) -> tuple:
    """将 analysis_call_edges 投影行转为 SQLite 参数。"""
    return (
        ce["call_edge_id"],
        aid,
        ce["from_node_id"],
        ce["to_node_id"],
        ce.get("to_class_name"),
        ce.get("to_method_name"),
        ce.get("resolution_type"),
        ce.get("confidence"),
        ce.get("source_file"),
        ce.get("source_start_line"),
        ce.get("source_start_column"),
        ce.get("source_end_line"),
        ce.get("source_end_column"),
    )


def row_to_call_edge(row: dict[str, Any]) -> dict[str, Any]:
    """将 analysis_call_edges 行转为投影 dict。"""
    return {
        "call_edge_id": row["call_edge_id"],
        "from_node_id": row["from_node_id"],
        "to_node_id": row["to_node_id"],
        "to_class_name": row.get("to_class_name"),
        "to_method_name": row.get("to_method_name"),
        "resolution_type": row.get("resolution_type"),
        "confidence": row.get("confidence"),
        "source_file": row.get("source_file"),
        "source_start_line": row.get("source_start_line"),
        "source_start_column": row.get("source_start_column"),
        "source_end_line": row.get("source_end_line"),
        "source_end_column": row.get("source_end_column"),
    }


def flow_to_row(aid: str, flow: dict[str, Any]) -> tuple:
    """将 analysis_execution_flows 投影行转为 SQLite 参数。"""
    return (
        flow["execution_flow_id"],
        aid,
        flow.get("execution_flow_fingerprint", ""),
        flow["entry_point"],
        flow.get("call_depth", 0),
    )


def row_to_flow(row: dict[str, Any]) -> dict[str, Any]:
    """将 analysis_execution_flows 行转为投影 dict。"""
    return {
        "execution_flow_id": row["execution_flow_id"],
        "execution_flow_fingerprint": row.get("execution_flow_fingerprint", ""),
        "entry_point": row["entry_point"],
        "call_depth": row.get("call_depth", 0),
    }


def flow_step_to_row(fid: str, step: dict[str, Any]) -> tuple:
    """将 analysis_flow_steps 投影行转为 SQLite 参数。"""
    return (
        step["flow_step_id"],
        fid,
        step["step_index"],
        step.get("depth", 0),
        step["method_key"],
        step.get("class_name"),
        step.get("method_name"),
        step.get("call_node_id"),
    )


def row_to_flow_step(row: dict[str, Any]) -> dict[str, Any]:
    """将 analysis_flow_steps 行转为投影 dict。"""
    # sqlite3.Row 没有 .get()，统一转 dict 后再读取（与其它 row_to_* 一致）
    if not isinstance(row, dict):
        row = dict(row)
    return {
        "flow_step_id": row.get("flow_step_id"),
        "execution_flow_id": row.get("execution_flow_id"),
        "step_index": row.get("step_index"),
        "depth": row.get("depth", 0),
        "method_key": row.get("method_key"),
        "class_name": row.get("class_name"),
        "method_name": row.get("method_name"),
        "call_node_id": row.get("call_node_id"),
    }


def cluster_to_row(aid: str, cluster: dict[str, Any]) -> tuple:
    """将 analysis_clusters 投影行转为 SQLite 参数。"""
    return (
        cluster["cluster_id"],
        aid,
        cluster.get("suggested_label", ""),
        json.dumps(cluster.get("member_keys", []), ensure_ascii=False),
        cluster.get("member_count", 0),
    )


def row_to_cluster(row: dict[str, Any]) -> dict[str, Any]:
    """将 analysis_clusters 行转为投影 dict。"""
    return {
        "cluster_id": row["cluster_id"],
        "analysis_id": row["analysis_id"],
        "suggested_label": row.get("suggested_label", ""),
        "member_keys": json.loads(row.get("member_keys_json") or "[]"),
        "member_count": row.get("member_count", 0),
    }
