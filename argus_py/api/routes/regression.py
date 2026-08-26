"""回归测试闭环 REST 路由。

路由保持薄层：schema 校验后调用 ``RegressionService``，错误统一映射为
稳定错误码。批次创建/取消是 async 服务方法（需与进程内队列交互），其余
经 ``run_in_thread`` 执行同步 SQLite 操作。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status

from argus_py.api.dependencies import get_regression_service
from argus_py.api.schemas.regression import (
    RegressionBaselineResponse,
    RegressionBaselineSetRequest,
    RegressionCaseCreateRequest,
    RegressionCaseListResponse,
    RegressionCaseResponse,
    RegressionCaseUpdateRequest,
    RegressionRunCreateRequest,
    RegressionRunDetailResponse,
    RegressionRunListResponse,
    RegressionRunResponse,
    RegressionRunSummaryResponse,
)
from argus_py.core.exceptions import ArgusError
from argus_py.observability.context import run_in_thread
from argus_py.regression.application import RegressionError
from argus_py.regression.enums import RegressionRunStatus

if TYPE_CHECKING:
    from argus_py.regression.application import RegressionService

router = APIRouter(tags=["regression"])


def _map_regression_error(exc: RegressionError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


def _map_known_errors(exc: Exception) -> HTTPException | None:
    """项目不存在等既有领域错误的统一映射。"""
    if isinstance(exc, RegressionError):
        return _map_regression_error(exc)
    from argus_py.core.exceptions import ProjectNotFoundError

    if isinstance(exc, ProjectNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": str(exc)},
        )
    if isinstance(exc, ArgusError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "REGRESSION_INVALID_INPUT", "message": str(exc)},
        )
    return None


# ══════════════════════════════════════════════════════════
# 回归用例
# ══════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/regression-cases",
    response_model=RegressionCaseListResponse,
)
async def list_regression_cases(
    project_id: str = Path(..., description="项目 ID"),
    enabled_only: bool = Query(default=False, alias="enabledOnly"),
    service: "RegressionService" = Depends(get_regression_service),
) -> RegressionCaseListResponse:
    """列出项目的回归用例（按 display_order 排序）。"""
    cases = await run_in_thread(service.list_cases, project_id, enabled_only=enabled_only)
    return RegressionCaseListResponse(
        total=len(cases),
        cases=[RegressionCaseResponse.from_case(c) for c in cases],
    )


@router.post(
    "/projects/{project_id}/regression-cases",
    response_model=RegressionCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_regression_case(
    project_id: str = Path(..., description="项目 ID"),
    request: RegressionCaseCreateRequest = Body(...),
    service: "RegressionService" = Depends(get_regression_service),
) -> RegressionCaseResponse:
    """创建回归用例（输入按任务创建同一套规则校验）。"""
    try:
        case = await run_in_thread(
            service.create_case, project_id, request.model_dump(by_alias=True)
        )
    except (RegressionError, ArgusError) as exc:
        mapped = _map_known_errors(exc)
        if mapped is not None:
            raise mapped from exc
        raise
    return RegressionCaseResponse.from_case(case)


@router.get("/regression-cases/{case_id}", response_model=RegressionCaseResponse)
async def get_regression_case(
    case_id: str = Path(..., description="用例 ID"),
    service: "RegressionService" = Depends(get_regression_service),
) -> RegressionCaseResponse:
    """获取回归用例详情。"""
    try:
        case = await run_in_thread(service.get_case, case_id)
    except RegressionError as exc:
        raise _map_regression_error(exc) from exc
    return RegressionCaseResponse.from_case(case)


@router.put("/regression-cases/{case_id}", response_model=RegressionCaseResponse)
async def update_regression_case(
    case_id: str = Path(..., description="用例 ID"),
    request: RegressionCaseUpdateRequest = Body(...),
    service: "RegressionService" = Depends(get_regression_service),
) -> RegressionCaseResponse:
    """更新回归用例（合并后整体重新校验）。"""
    updates = request.model_dump(exclude_unset=True, by_alias=True)
    try:
        case = await run_in_thread(service.update_case, case_id, updates)
    except RegressionError as exc:
        raise _map_regression_error(exc) from exc
    except ArgusError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "REGRESSION_INVALID_INPUT", "message": str(exc)},
        ) from exc
    return RegressionCaseResponse.from_case(case)


@router.delete("/regression-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_regression_case(
    case_id: str = Path(..., description="用例 ID"),
    service: "RegressionService" = Depends(get_regression_service),
) -> None:
    """删除回归用例（历史批次使用快照，不受影响）。"""
    try:
        await run_in_thread(service.delete_case, case_id)
    except RegressionError as exc:
        raise _map_regression_error(exc) from exc


# ══════════════════════════════════════════════════════════
# 回归批次
# ══════════════════════════════════════════════════════════


@router.post(
    "/projects/{project_id}/regression-runs",
    response_model=RegressionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_regression_run(
    project_id: str = Path(..., description="项目 ID"),
    request: RegressionRunCreateRequest | None = Body(default=None),
    service: "RegressionService" = Depends(get_regression_service),
) -> RegressionRunResponse:
    """创建并启动回归批次（异步执行；轮询批次状态获取进度与结论）。"""
    triggered_by = request.triggered_by if request is not None else None
    try:
        run = await service.create_run(project_id, trigger_source="api", triggered_by=triggered_by)
    except RegressionError as exc:
        raise _map_regression_error(exc) from exc
    return RegressionRunResponse.from_run(run)


@router.get(
    "/projects/{project_id}/regression-runs",
    response_model=RegressionRunListResponse,
)
async def list_regression_runs(
    project_id: str = Path(..., description="项目 ID"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, gt=0, le=100),
    run_status: str | None = Query(default=None, alias="status"),
    service: "RegressionService" = Depends(get_regression_service),
) -> RegressionRunListResponse:
    """分页查询项目批次历史（created_at 倒序）。"""
    parsed_status: RegressionRunStatus | None = None
    if run_status:
        try:
            parsed_status = RegressionRunStatus(run_status)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "REGRESSION_INVALID_INPUT",
                    "message": f"未知批次状态：{run_status}",
                },
            ) from exc
    runs, total = await run_in_thread(
        service.list_runs, project_id, offset=offset, limit=limit, status=parsed_status
    )
    return RegressionRunListResponse(
        total=total,
        runs=[RegressionRunResponse.from_run(r) for r in runs],
        offset=offset,
        limit=limit,
    )


@router.get("/regression-runs/{run_id}", response_model=RegressionRunDetailResponse)
async def get_regression_run(
    run_id: str = Path(..., description="批次 ID"),
    service: "RegressionService" = Depends(get_regression_service),
) -> RegressionRunDetailResponse:
    """获取批次详情（含批次项实时任务状态与持久化汇总）。"""
    try:
        run = await run_in_thread(service.get_run, run_id)
        items = await run_in_thread(service.get_run_items, run_id)
        summary_raw = await run_in_thread(service.get_run_summary, run_id)
    except RegressionError as exc:
        raise _map_regression_error(exc) from exc
    return RegressionRunDetailResponse(
        run=RegressionRunResponse.from_run(run),
        items=items,
        summary=RegressionRunSummaryResponse(**summary_raw)
        if summary_raw
        else RegressionRunSummaryResponse(),
    )


@router.get("/regression-runs/{run_id}/summary", response_model=RegressionRunSummaryResponse)
async def get_regression_run_summary(
    run_id: str = Path(..., description="批次 ID"),
    service: "RegressionService" = Depends(get_regression_service),
) -> RegressionRunSummaryResponse:
    """获取批次汇总（差异明细、门禁原因、计数）。"""
    try:
        summary_raw = await run_in_thread(service.get_run_summary, run_id)
    except RegressionError as exc:
        raise _map_regression_error(exc) from exc
    return RegressionRunSummaryResponse(**summary_raw)


@router.post("/regression-runs/{run_id}/cancel", response_model=RegressionRunResponse)
async def cancel_regression_run(
    run_id: str = Path(..., description="批次 ID"),
    service: "RegressionService" = Depends(get_regression_service),
) -> RegressionRunResponse:
    """取消未完成批次（未执行子任务取消，已执行的尽力中断）。"""
    try:
        run = await service.cancel_run(run_id)
    except RegressionError as exc:
        raise _map_regression_error(exc) from exc
    return RegressionRunResponse.from_run(run)


# ══════════════════════════════════════════════════════════
# 项目基线
# ══════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/regression-baseline",
    response_model=RegressionBaselineResponse,
)
async def get_regression_baseline(
    project_id: str = Path(..., description="项目 ID"),
    service: "RegressionService" = Depends(get_regression_service),
) -> RegressionBaselineResponse:
    """读取项目当前基线批次。"""
    baseline = await run_in_thread(service.get_baseline, project_id)
    return RegressionBaselineResponse(baseline_run_id=baseline.run_id if baseline else None)


@router.put(
    "/projects/{project_id}/regression-baseline",
    response_model=RegressionBaselineResponse,
)
async def set_regression_baseline(
    project_id: str = Path(..., description="项目 ID"),
    request: RegressionBaselineSetRequest = Body(...),
    service: "RegressionService" = Depends(get_regression_service),
) -> RegressionBaselineResponse:
    """将成功批次设为项目基线（仅 completed 批次；每项目一个基线）。"""
    try:
        run = await run_in_thread(service.set_baseline, request.run_id)
    except RegressionError as exc:
        raise _map_regression_error(exc) from exc
    if run.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BASELINE_PROJECT_MISMATCH",
                "message": f"批次 {request.run_id} 不属于项目 {project_id}。",
            },
        )
    return RegressionBaselineResponse(baseline_run_id=run.run_id)
