"""诊断中心查询路由（docs/optimizations/diagnostics-center-plan.md 第 17 章）。

只做 IO 适配 + API 序列化；日志扫描在仓储内完成并经 ``run_in_thread``
进入线程池。所有查询接口统一走 ``_guarded``：并发上限超限立即返回 429，
单次查询超时返回 503，不排队堆积（单 worker 资源隔离约束）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from argus_py.api.dependencies import (
    get_diagnostics_semaphore,
    get_diagnostics_service,
    get_diagnostics_store,
    get_server_settings,
)
from argus_py.api.schemas import (
    DiagnosticsContextResponse,
    DiagnosticsEventsPage,
    DiagnosticsLogDetail,
    DiagnosticsLogEntry,
    DiagnosticsLogPage,
    DiagnosticsOverviewResponse,
    DiagnosticsServicesResponse,
    DiagnosticsSystemInfoResponse,
    DiagnosticsTraceResponse,
    FrontendEventRequest,
    FrontendEventResponse,
    LogsUsageResponse,
    RunsListResponse,
    RunSummaryResponse,
    ServiceStatusResponse,
)
from argus_py.config.server_settings import ServerSettings
from argus_py.observability.context import run_in_thread
from argus_py.observability.diagnostics_service import DiagnosticsService, ServiceStatus
from argus_py.observability.diagnostics_store import (
    DiagnosticsBadRequestError,
    DiagnosticsNotFoundError,
    DiagnosticsQuery,
)
from argus_py.observability.frontend_events import append_frontend_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

_MAX_LIMIT_DEFAULT = 200

SemaphoreDep = Annotated[asyncio.Semaphore, Depends(get_diagnostics_semaphore)]
SettingsDep = Annotated[ServerSettings, Depends(get_server_settings)]
StoreDep = Annotated[Any, Depends(get_diagnostics_store)]
ServiceDep = Annotated[DiagnosticsService, Depends(get_diagnostics_service)]


async def _guarded(
    semaphore: asyncio.Semaphore,
    settings: ServerSettings,
    operation: str,
    func: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """并发闸门 + 超时保护：429 快速失败、503 超时（方案第 17 章）。

    ``locked()`` 预检与 ``acquire`` 之间存在固有 TOCTOU 窗口：并发边界上的
    个别请求可能短暂排队而非快速 429。这是无阻塞 acquire 语义下可接受的
    近似——闸门仍保证同时在途查询数不超过上限。
    """
    if semaphore.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="诊断查询并发已达上限，请稍后重试或缩小查询范围。",
        )
    async with semaphore:
        try:
            return await asyncio.wait_for(
                run_in_thread(func, *args, **kwargs),
                timeout=settings.diagnostics_query_timeout_seconds,
            )
        except TimeoutError as exc:
            logger.warning("诊断查询超时：%s", operation)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"诊断查询超时（>{settings.diagnostics_query_timeout_seconds:.0f}s），请缩小时间范围。",
            ) from exc
        except (DiagnosticsNotFoundError, DiagnosticsBadRequestError):
            # 非法游标/组件/事件 ID 等业务校验错误在仓储内抛出，交由调用方映射。
            raise


async def _guarded_or_40x(
    semaphore: asyncio.Semaphore,
    settings: ServerSettings,
    operation: str,
    func: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """``_guarded`` + 仓储层 400/404 错误统一映射。"""
    try:
        return await _guarded(semaphore, settings, operation, func, *args, **kwargs)
    except (DiagnosticsNotFoundError, DiagnosticsBadRequestError) as exc:
        raise _to_http_error(exc) from exc


def _to_http_error(exc: DiagnosticsNotFoundError | DiagnosticsBadRequestError) -> HTTPException:
    if isinstance(exc, DiagnosticsNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _query_from_params(
    time_from: datetime | None,
    time_to: datetime | None,
    component: str | None,
    level: str | None,
    keyword: str | None,
    request_id: str | None,
    run_id: str | None,
    limit: int,
    cursor: str | None,
) -> DiagnosticsQuery:
    try:
        return DiagnosticsQuery(
            time_from=time_from,
            time_to=time_to,
            component=component,
            level=level,
            keyword=keyword,
            request_id=request_id,
            run_id=run_id,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        # DiagnosticsBadRequestError 是 ValueError 子类，非法组件名在此转 400。
        raise _to_http_error(DiagnosticsBadRequestError(str(exc))) from exc


# ── 服务状态 ────────────────────────────────────────────────────────────────


@router.get("/services", response_model=DiagnosticsServicesResponse)
async def get_services(
    service: ServiceDep,
) -> DiagnosticsServicesResponse:
    """返回各组件健康状态与日志目录占用（方案 17.2）。"""
    python_or_err: BaseException | ServiceStatus
    db_or_err: BaseException | ServiceStatus
    console_or_err: BaseException | ServiceStatus
    usage_or_err: BaseException | dict[str, Any]
    python_or_err, db_or_err, console_or_err, usage_or_err = await asyncio.gather(
        run_in_thread(service.python_status),
        run_in_thread(service.db_status),
        run_in_thread(service.console_status),
        run_in_thread(service.logs_usage),
        return_exceptions=True,
    )

    def _ok(value: Any, fallback_name: str) -> ServiceStatusResponse:
        if isinstance(value, BaseException):
            return ServiceStatusResponse(name=fallback_name, status="unknown", detail=str(value))
        return ServiceStatusResponse(**value.to_wire())

    services = [
        _ok(python_or_err, "python"),
        ServiceStatusResponse(**(await service.java_status()).to_wire()),
        _ok(db_or_err, "database"),
        _ok(console_or_err, "web"),
    ]
    logs_usage = None
    if isinstance(usage_or_err, BaseException):
        services.append(
            ServiceStatusResponse(name="logs", status="unknown", detail=str(usage_or_err))
        )
    else:
        logs_usage = LogsUsageResponse(**usage_or_err)
    return DiagnosticsServicesResponse(
        services=services,
        logs_usage=logs_usage,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


# ── 日志查询 ────────────────────────────────────────────────────────────────


@router.get("/logs", response_model=DiagnosticsLogPage)
async def search_logs(
    store: StoreDep,
    semaphore: SemaphoreDep,
    settings: SettingsDep,
    time_from: datetime | None = Query(default=None, alias="from"),
    time_to: datetime | None = Query(default=None, alias="to"),
    component: str | None = Query(default=None, max_length=20),
    level: str | None = Query(default=None, max_length=10),
    keyword: str | None = Query(default=None, max_length=200),
    request_id: str | None = Query(default=None, alias="requestId", max_length=128),
    run_id: str | None = Query(default=None, alias="runId", max_length=64),
    limit: int = Query(default=100, ge=1, le=_MAX_LIMIT_DEFAULT),
    cursor: str | None = Query(default=None, max_length=512),
) -> DiagnosticsLogPage:
    """按条件检索诊断日志，游标分页、新→旧（方案 8.2/8.6/17.3）。"""
    query = _query_from_params(
        time_from, time_to, component, level, keyword, request_id, run_id, limit, cursor
    )
    page = await _guarded_or_40x(semaphore, settings, "logs.search", store.search, query)
    return DiagnosticsLogPage(**page.to_wire())


@router.get("/logs/{event_id}/context", response_model=DiagnosticsContextResponse)
async def get_log_context(
    event_id: str,
    store: StoreDep,
    semaphore: SemaphoreDep,
    settings: SettingsDep,
    before: int = Query(default=20, ge=0, le=200),
    after: int = Query(default=20, ge=0, le=200),
) -> DiagnosticsContextResponse:
    """返回同文件内前后若干条日志上下文（方案 17.5）。"""
    items = await _guarded_or_40x(
        semaphore, settings, "logs.context", store.get_context, event_id, before, after
    )
    return DiagnosticsContextResponse(items=[DiagnosticsLogEntry(**e.to_wire()) for e in items])


@router.get("/logs/{event_id}", response_model=DiagnosticsLogDetail)
async def get_log_detail(
    event_id: str,
    store: StoreDep,
    semaphore: SemaphoreDep,
    settings: SettingsDep,
) -> DiagnosticsLogDetail:
    """返回单条日志完整内容（含原始 JSON 与文件来源，方案 17.4）。"""
    detail = await _guarded_or_40x(semaphore, settings, "logs.detail", store.get_detail, event_id)
    entry: dict[str, Any] = detail["event"].to_wire()
    entry["raw"] = detail["raw"]
    entry["source"] = detail["source"]
    return DiagnosticsLogDetail(**entry)


# ── 请求追踪 ────────────────────────────────────────────────────────────────


@router.get("/requests/{request_id}", response_model=DiagnosticsTraceResponse)
async def trace_request(
    request_id: str,
    store: StoreDep,
    semaphore: SemaphoreDep,
    settings: SettingsDep,
    limit: int = Query(default=200, ge=1, le=_MAX_LIMIT_DEFAULT),
) -> DiagnosticsTraceResponse:
    """按 Request ID 还原一次请求的完整处理过程（方案 17.6），时间正序。"""
    items = await _guarded_or_40x(
        semaphore,
        settings,
        "requests.trace",
        store.search_by_request_id,
        request_id,
        limit,
    )
    return DiagnosticsTraceResponse(
        request_id=request_id, items=[DiagnosticsLogEntry(**e.to_wire()) for e in items]
    )


# ── 启动会话 ────────────────────────────────────────────────────────────────


@router.get("/runs", response_model=RunsListResponse)
async def list_runs(
    store: StoreDep,
    semaphore: SemaphoreDep,
    settings: SettingsDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> RunsListResponse:
    """列出启动会话，新会话在前（方案 17.7）。"""
    runs = await _guarded_or_40x(semaphore, settings, "runs.list", store.list_runs, limit)
    return RunsListResponse(runs=[RunSummaryResponse(**r.to_wire()) for r in runs])


@router.get("/runs/{run_id}", response_model=RunSummaryResponse)
async def get_run(
    run_id: str,
    store: StoreDep,
    semaphore: SemaphoreDep,
    settings: SettingsDep,
) -> RunSummaryResponse:
    """返回单个启动会话元数据。"""
    run = await _guarded_or_40x(semaphore, settings, "runs.detail", store.get_run_detail, run_id)
    return RunSummaryResponse(**run.to_wire())


@router.get("/runs/{run_id}/logs", response_model=DiagnosticsLogPage)
async def search_run_logs(
    run_id: str,
    store: StoreDep,
    semaphore: SemaphoreDep,
    settings: SettingsDep,
    time_from: datetime | None = Query(default=None, alias="from"),
    time_to: datetime | None = Query(default=None, alias="to"),
    component: str | None = Query(default=None, max_length=20),
    level: str | None = Query(default=None, max_length=10),
    keyword: str | None = Query(default=None, max_length=200),
    request_id: str | None = Query(default=None, alias="requestId", max_length=128),
    limit: int = Query(default=100, ge=1, le=_MAX_LIMIT_DEFAULT),
    cursor: str | None = Query(default=None, max_length=512),
) -> DiagnosticsLogPage:
    """检索指定启动会话内的日志（方案 17.7 runs/{runId}/logs）。"""
    query = _query_from_params(
        time_from, time_to, component, level, keyword, request_id, None, limit, cursor
    )
    page = await _guarded_or_40x(
        semaphore, settings, "runs.logs", store.search_run_logs, run_id, query
    )
    return DiagnosticsLogPage(**page.to_wire())


# ── 概览 / 系统信息 / 系统事件 / 前端异常 ──────────────────────────────────


@router.get("/overview", response_model=DiagnosticsOverviewResponse)
async def get_overview(
    service: ServiceDep,
    semaphore: SemaphoreDep,
    settings: SettingsDep,
) -> DiagnosticsOverviewResponse:
    """诊断概览：服务摘要、近 1h ERROR 近似计数、系统事件与日志用量。"""
    overview = await _guarded_or_40x(semaphore, settings, "overview", service.overview_sync)
    java = await service.java_status()
    services = list(overview.get("services") or [])
    services.insert(1, java.to_wire())
    logs_usage = overview.get("logsUsage")
    return DiagnosticsOverviewResponse(
        run_id=str(overview.get("runId") or ""),
        services=[ServiceStatusResponse(**item) for item in services],
        logs_usage=LogsUsageResponse(**logs_usage) if isinstance(logs_usage, dict) else None,
        error_count_last_hour=int(overview.get("errorCountLastHour") or 0),
        recent_system_events=[
            DiagnosticsLogEntry(**item) for item in (overview.get("recentSystemEvents") or [])
        ],
        checked_at=str(overview.get("checkedAt") or datetime.now(timezone.utc).isoformat()),
    )


@router.get("/system", response_model=DiagnosticsSystemInfoResponse)
async def get_system_info(
    service: ServiceDep,
    semaphore: SemaphoreDep,
    settings: SettingsDep,
) -> DiagnosticsSystemInfoResponse:
    """系统信息（方案 17.10），附带当前 Java 健康快照。"""
    info = await _guarded_or_40x(semaphore, settings, "system.info", service.system_info)
    java = await service.java_status()
    payload = dict(info)
    payload["javaStatus"] = java.to_wire()
    return DiagnosticsSystemInfoResponse.model_validate(payload)


@router.get("/events", response_model=DiagnosticsEventsPage)
async def list_system_events(
    store: StoreDep,
    semaphore: SemaphoreDep,
    settings: SettingsDep,
    time_from: datetime | None = Query(default=None, alias="from"),
    time_to: datetime | None = Query(default=None, alias="to"),
    level: str | None = Query(default=None, max_length=10),
    keyword: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=_MAX_LIMIT_DEFAULT),
    cursor: str | None = Query(default=None, max_length=512),
) -> DiagnosticsEventsPage:
    """系统事件流（投影 runtime/system JSONL，方案 17.9）。"""
    query = _query_from_params(
        time_from, time_to, "system", level, keyword, None, None, limit, cursor
    )
    page = await _guarded_or_40x(semaphore, settings, "events.list", store.search, query)
    return DiagnosticsEventsPage(**page.to_wire())


@router.post(
    "/frontend-events",
    response_model=FrontendEventResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_frontend_event(
    body: FrontendEventRequest,
    store: StoreDep,
    semaphore: SemaphoreDep,
    settings: SettingsDep,
) -> FrontendEventResponse:
    """接收前端未捕获异常（方案 17.8）；有界写入 runtime/web JSONL。"""

    def _write() -> dict[str, Any]:
        return append_frontend_event(
            body.model_dump(by_alias=True, exclude_none=True),
            logs_root=store.logs_root,
        )

    record = await _guarded(semaphore, settings, "frontend-events.write", _write)
    return FrontendEventResponse(accepted=True, event_id=record.get("eventId"))
