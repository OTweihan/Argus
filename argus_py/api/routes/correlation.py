"""黑白盒关联 REST API 路由 — 以 correlation_run_id 为中心。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status

from argus_py.api.dependencies import get_correlation_service, get_task_app_service
from argus_py.api.schemas.correlation import (
    BindAnalysisRequest,
    CaptureQualityResponse,
    CorrelationAttemptListResponse,
    CorrelationAttemptResponse,
    CorrelationRunResponse,
    CorrelationSummaryResponse,
    EndpointEvidencePageResponse,
    EndpointEvidenceResponse,
    FindingEvidencePageResponse,
    FindingEvidenceResponse,
    HttpRequestEvidencePageResponse,
    HttpRequestEvidenceResponse,
    UncoveredEndpointPageResponse,
)
from argus_py.observability.context import run_in_thread
from argus_py.task.application import TaskApplicationService

if TYPE_CHECKING:
    from argus_py.correlation.application import CorrelationService

router = APIRouter(prefix="/correlation-runs", tags=["correlation"])


def _not_found(entity: str, entity_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": f"{entity}_NOT_FOUND", "message": f"{entity} 不存在：{entity_id}"},
    )


# ════════════════════════════════════════════════════════════════
# CorrelationRun
# ════════════════════════════════════════════════════════════════


@router.get("/{correlation_run_id}", response_model=CorrelationRunResponse)
async def get_correlation_run(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> CorrelationRunResponse:
    """获取关联运行详情。"""
    data = await run_in_thread(app.get_correlation_run, correlation_run_id)
    if data is None:
        raise _not_found("CorrelationRun", correlation_run_id)
    return CorrelationRunResponse(**data)


# ════════════════════════════════════════════════════════════════
# Attempts
# ════════════════════════════════════════════════════════════════


@router.get("/{correlation_run_id}/attempts", response_model=CorrelationAttemptListResponse)
async def list_attempts(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> CorrelationAttemptListResponse:
    """列出关联运行的所有尝试记录。"""
    items = await run_in_thread(app.list_correlation_attempts, correlation_run_id)
    return CorrelationAttemptListResponse(
        items=[CorrelationAttemptResponse(**it) for it in items],
        total=len(items),
    )


@router.get(
    "/{correlation_run_id}/attempts/{attempt_id}",
    response_model=CorrelationAttemptResponse,
)
async def get_attempt(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    attempt_id: str = Path(..., description="尝试 ID"),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> CorrelationAttemptResponse:
    """获取单次尝试详情。"""
    data = await run_in_thread(app.get_correlation_attempt, correlation_run_id, attempt_id)
    if data is None:
        raise _not_found("CorrelationAttempt", attempt_id)
    return CorrelationAttemptResponse(**data)


# ════════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════════


@router.get("/{correlation_run_id}/summary", response_model=CorrelationSummaryResponse)
async def get_summary(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> CorrelationSummaryResponse:
    """获取关联汇总指标。"""
    data = await run_in_thread(app.get_correlation_summary, correlation_run_id)
    return CorrelationSummaryResponse(**data)


# ════════════════════════════════════════════════════════════════
# Endpoint Evidence
# ════════════════════════════════════════════════════════════════


@router.get(
    "/{correlation_run_id}/endpoint-evidence",
    response_model=EndpointEvidencePageResponse,
)
async def list_endpoint_evidence(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    resolution_status: str | None = Query(
        default=None, alias="resolutionStatus", description="过滤匹配结果状态"
    ),
    match_strategy: str | None = Query(
        default=None, alias="matchStrategy", description="过滤匹配方式"
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, gt=0, le=500),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> EndpointEvidencePageResponse:
    """分页查询端点匹配证据。"""
    items, total = await run_in_thread(
        app.list_endpoint_evidence,
        correlation_run_id,
        resolution_status=resolution_status,
        match_strategy=match_strategy,
        offset=offset,
        limit=limit,
    )
    return EndpointEvidencePageResponse(
        items=[EndpointEvidenceResponse(**it) for it in items],
        total=total,
        has_more=(offset + limit) < total,
    )


# ════════════════════════════════════════════════════════════════
# Unmatched Requests
# ════════════════════════════════════════════════════════════════


@router.get(
    "/{correlation_run_id}/unmatched-requests",
    response_model=HttpRequestEvidencePageResponse,
)
async def list_unmatched_requests(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, gt=0, le=500),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> HttpRequestEvidencePageResponse:
    """获取无法匹配到白盒端点的 HTTP 请求列表。"""
    items, total = await run_in_thread(
        app.list_unmatched_requests,
        correlation_run_id,
        offset=offset,
        limit=limit,
    )
    return HttpRequestEvidencePageResponse(
        items=[HttpRequestEvidenceResponse(**it) for it in items],
        total=total,
        has_more=(offset + limit) < total,
    )


# ════════════════════════════════════════════════════════════════
# Finding Evidence
# ════════════════════════════════════════════════════════════════


@router.get(
    "/{correlation_run_id}/finding-evidence",
    response_model=FindingEvidencePageResponse,
)
async def list_finding_evidence(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, gt=0, le=500),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> FindingEvidencePageResponse:
    """获取 Finding 关联证据。"""
    items, total = await run_in_thread(
        app.list_finding_evidence,
        correlation_run_id,
        offset=offset,
        limit=limit,
    )
    return FindingEvidencePageResponse(
        items=[FindingEvidenceResponse(**it) for it in items],
        total=total,
        has_more=(offset + limit) < total,
    )


# ════════════════════════════════════════════════════════════════
# Capture Quality
# ════════════════════════════════════════════════════════════════


@router.get(
    "/{correlation_run_id}/capture-quality",
    response_model=CaptureQualityResponse,
)
async def get_capture_quality(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> CaptureQualityResponse:
    """获取采集质量统计。"""
    cr = await run_in_thread(app.get_correlation_run, correlation_run_id)
    if cr is None:
        raise _not_found("CorrelationRun", correlation_run_id)
    bb_id = cr.get("blackboxRunId", "")
    data = await run_in_thread(app.get_capture_quality, bb_id)
    if data is None:
        raise _not_found("CaptureQuality", bb_id)
    return CaptureQualityResponse(**data)


# ════════════════════════════════════════════════════════════════
# Uncovered Endpoints
# ════════════════════════════════════════════════════════════════


@router.get(
    "/{correlation_run_id}/uncovered-endpoints",
    response_model=UncoveredEndpointPageResponse,
)
async def list_uncovered_endpoints(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, gt=0, le=500),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> UncoveredEndpointPageResponse:
    """获取未被任何请求命中的白盒端点列表。"""
    items, total = await run_in_thread(
        app.list_uncovered_endpoints,
        correlation_run_id,
        offset=offset,
        limit=limit,
    )
    return UncoveredEndpointPageResponse(
        items=items,
        total=total,
        has_more=(offset + limit) < total if total is not None else False,
    )


# ════════════════════════════════════════════════════════════════
# Task-level lookup (no correlation_run_id needed)
# ════════════════════════════════════════════════════════════════


@router.get("")
async def list_correlation_runs_by_task(
    task_id: str = Query(..., alias="taskId", description="任务 ID"),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> list[CorrelationRunResponse]:
    """通过 taskId 查找关联运行列表。"""
    items = await run_in_thread(app.list_correlation_runs_by_task, task_id)
    return [CorrelationRunResponse(**it) for it in items]


# ════════════════════════════════════════════════════════════════
# 操作
# ════════════════════════════════════════════════════════════════


@router.post("/{correlation_run_id}/bind-analysis", status_code=status.HTTP_204_NO_CONTENT)
async def bind_analysis(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    body: BindAnalysisRequest = Body(...),
    correlation: "CorrelationService" = Depends(get_correlation_service),
) -> None:
    """绑定白盒分析到关联运行。"""
    try:
        await run_in_thread(
            correlation.bind_analysis,
            correlation_run_id,
            body.analysis_id,
            expected_projection_version=body.expected_projection_version,
            source_mismatch_override=body.source_mismatch_override,
            source_mismatch_override_reason=body.source_mismatch_override_reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "BIND_FAILED", "message": str(exc)},
        ) from exc


@router.post("/{correlation_run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_correlation(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    correlation: "CorrelationService" = Depends(get_correlation_service),
) -> dict[str, str]:
    """重试关联（相同输入，创建新 Attempt）。"""
    try:
        attempt_id = await run_in_thread(correlation.retry_correlation, correlation_run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "RETRY_FAILED", "message": str(exc)},
        ) from exc
    return {"correlationAttemptId": attempt_id}


@router.post("/{correlation_run_id}/recalculate", status_code=status.HTTP_201_CREATED)
async def recalculate_correlation(
    correlation_run_id: str = Path(..., description="关联运行 ID"),
    correlation: "CorrelationService" = Depends(get_correlation_service),
) -> CorrelationRunResponse:
    """重算关联（输入变化，创建新 CorrelationRun）。"""
    try:
        data = await run_in_thread(correlation.recalculate_correlation, correlation_run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "RECALC_FAILED", "message": str(exc)},
        ) from exc
    if data is None:
        raise _not_found("CorrelationRun", correlation_run_id)
    return CorrelationRunResponse(**data)
