"""测试工厂 — 请求证据、采集质量。"""

from __future__ import annotations

from argus_py.correlation.enums import (
    CorrelationEligibility,
    RequestOutcome,
    RequestOwner,
)
from argus_py.correlation.models import CaptureQuality, HttpRequestEvidence


def make_http_request_evidence(
    request_evidence_id: str = "req-1",
    blackbox_run_id: str = "bb-1",
    task_id: str = "t-1",
    step_execution_id: str | None = None,
    request_sequence: int = 1,
    http_method: str = "GET",
    normalized_path: str = "/api/users",
    display_path: str | None = None,
    origin: str = "https://example.com",
    endpoint_match_eligibility: CorrelationEligibility = CorrelationEligibility.CONFIRMED_ELIGIBLE,
    outcome: RequestOutcome = RequestOutcome.COMPLETED,
    request_owner: RequestOwner = RequestOwner.FRAME,
    response_from_service_worker: bool = False,
    captured_at: str = "2024-01-01T00:00:00",
    **overrides,
) -> HttpRequestEvidence:
    """创建最小化 HttpRequestEvidence，默认值为合法实体。

    测试仅需覆盖变化的字段。
    """
    return HttpRequestEvidence(
        request_evidence_id=request_evidence_id,
        blackbox_run_id=blackbox_run_id,
        task_id=task_id,
        step_execution_id=step_execution_id,
        request_sequence=request_sequence,
        http_method=http_method,
        normalized_path=normalized_path,
        display_path=display_path or normalized_path,
        origin=origin,
        endpoint_match_eligibility=endpoint_match_eligibility,
        outcome=outcome,
        request_owner=request_owner,
        response_from_service_worker=response_from_service_worker,
        captured_at=captured_at,
        **overrides,
    )


def make_capture_quality(
    blackbox_run_id: str = "bb-1",
    total_observed: int = 100,
    accepted_started: int = 95,
    persisted_count: int = 90,
    filtered_by_resource_type: int = 3,
    filtered_cross_origin: int = 2,
    filtered_by_method: int = 1,
    filtered_path_too_long: int = 1,
    dropped_pending_limit: int = 2,
    dropped_run_limit: int = 1,
    persistence_failed: int = 0,
    truncated: bool = False,
    truncation_reason: str | None = None,
    updated_at: str = "2024-01-01T00:00:00",
    **overrides,
) -> CaptureQuality:
    """创建最小化 CaptureQuality，默认值为合法实体。"""
    return CaptureQuality(
        blackbox_run_id=blackbox_run_id,
        total_observed=total_observed,
        accepted_started=accepted_started,
        persisted_count=persisted_count,
        filtered_by_resource_type=filtered_by_resource_type,
        filtered_cross_origin=filtered_cross_origin,
        filtered_by_method=filtered_by_method,
        filtered_path_too_long=filtered_path_too_long,
        dropped_pending_limit=dropped_pending_limit,
        dropped_run_limit=dropped_run_limit,
        persistence_failed=persistence_failed,
        truncated=truncated,
        truncation_reason=truncation_reason,
        updated_at=updated_at,
        **overrides,
    )
