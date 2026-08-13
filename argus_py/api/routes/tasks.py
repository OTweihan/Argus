"""任务 REST API 路由 — 只做参数/响应转换，业务编排委托 TaskApplicationService。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from argus_py.api.dependencies import get_task_app_service
from argus_py.api.params import TaskIdPath
from argus_py.api.schemas import (
    DashboardStatsResponse,
    InferredLimitsResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskStartResponse,
    TaskSummaryListResponse,
    TaskSummaryResponse,
    TaskUpdateRequest,
)
from argus_py.api.schemas.analysis import (
    AnalysisRunListResponse,
    AnalysisRunSummaryResponse,
    CallEdgeResponse,
    CallGraphPageResponse,
    CallNodePageResponse,
    CallNodeResponse,
    ClusterPageResponse,
    ClusterResponse,
    CompletenessMetricsResponse,
    CompletenessResponse,
    DiagnosticsResponse,
    EndpointPageResponse,
    EndpointResponse,
    ExecutionFlowPageResponse,
    ExecutionFlowResponse,
    ExecutionFlowStepResponse,
    FindingDetailResponse,
    FindingPageResponse,
    QualityIssueResponse,
    SourceLocationResponse,
)
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.observability.context import run_in_thread
from argus_py.task.application import TaskAppError, TaskApplicationService
from argus_py.task.strategy import infer_execution_limits

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _to_http_exception(e: TaskAppError) -> HTTPException:
    """TaskAppError → HTTPException，满载类错误透传 Retry-After 头。"""
    headers: dict[str, str] = {}
    retry_after = e.details.get("retry_after_seconds")
    if isinstance(retry_after, (int, float)) and retry_after > 0:
        headers["Retry-After"] = str(int(retry_after))
    return HTTPException(
        status_code=e.http_status,
        detail=e.to_http_detail(),
        headers=headers or None,
    )


async def _acall_sync(
    fn: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """在线程池中调用同步应用层方法，TaskAppError 自动转为 HTTPException。

    ``asyncio.to_thread`` 把阻塞 SQLite / 文件 IO 移出事件循环，避免并发请求
    互相阻塞。``TaskAppError`` 通过 ``to_thread`` 在线程内抛出，由 ``await`` 处
    重新抛到协程上下文，再被本函数转换。HTTP 状态码以 ``TaskAppError.http_status``
    为准，无需外部传入。
    """
    try:
        return await run_in_thread(fn, *args, **kwargs)
    except TaskAppError as e:
        raise _to_http_exception(e)


async def _acall(
    fn: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """调用异步应用层方法，TaskAppError 自动转为 HTTPException。"""
    try:
        return await fn(*args, **kwargs)
    except TaskAppError as e:
        raise _to_http_exception(e)


async def _resolve_create_params(
    app: TaskApplicationService,
    request: Any,
) -> dict[str, Any]:
    """提取 create/update 请求的公共字段并解析为 create 参数。

    ``resolve_create_params`` 内部读取 project + model_config（同步 SQLite），
    与后续 create/update 一起放线程池执行，避免事件循环被任一阶段阻塞。
    """
    return await run_in_thread(
        app.resolve_create_params,
        goal=request.goal,
        name=request.name,
        start_url=request.start_url,
        task_type=request.task_type,
        project_id=request.project_id,
        max_steps=request.max_steps,
        timeout_seconds=request.timeout_seconds,
        capture_screenshots=request.capture_screenshots,
        model_config_id=request.model_config_id,
        parameters=request.parameters,
        whitebox_config=request.whitebox_config,
    )


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    request: TaskCreateRequest,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """创建任务快照，不立即启动执行。"""
    params = await _resolve_create_params(app, request)
    task = await _acall_sync(app.create_task, **params)
    return TaskResponse.from_task(task)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    request: TaskUpdateRequest,
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """更新待执行任务的基础信息。"""
    params = await _resolve_create_params(app, request)
    # name 三态语义：未显式提供 → 保持原名（resolve_create_params 返回 dict 恒含
    # name，此处弹出后走 lifecycle 的 _UNSET 默认值）；显式传 null/空串/纯空白 →
    # 由 lifecycle 归一化为任务 ID 后 8 位；正常值 → 去除首尾空白后使用。
    if "name" not in request.model_fields_set:
        params.pop("name", None)
    updated, sched = await _acall(app.update_task, task_id, params)
    return TaskResponse.from_task(updated, scheduler_status=sched)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> Response:
    """删除未启动的 pending 任务。"""
    await _acall(app.delete_task, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=TaskSummaryListResponse)
async def list_tasks(
    status: TaskStatus | None = None,
    project_id: str | None = Query(default=None, alias="projectId"),
    task_type: TaskType | None = Query(default=None, alias="taskType"),
    q: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, gt=0, le=200),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskSummaryListResponse:
    """列出任务（轻量，不含日志和发现项），支持过滤和分页。"""
    # 单 SQL 语句同时返回列表与总量：COUNT(*) OVER() 窗口函数避免
    # 两次往返，也不必再走 count_tasks。
    tasks, total = await run_in_thread(
        app.list_task_summaries,
        status=status,
        project_id=project_id,
        task_type=task_type,
        offset=offset,
        limit=limit,
        q=q,
    )
    status_snapshot = await app.snapshot_queue_statuses()
    return TaskSummaryListResponse(
        total=total,
        tasks=[
            TaskSummaryResponse.from_task(task, scheduler_status=status_snapshot.get(task.task_id))
            for task in tasks
        ],
    )


@router.get("/infer-limits", response_model=InferredLimitsResponse)
async def infer_limits(
    goal: str = Query(..., min_length=1),
    start_url: str | None = Query(default=None),
) -> InferredLimitsResponse:
    """根据任务目标和起始 URL 推断推荐的最大步数和超时时间。"""
    limits = infer_execution_limits(goal, start_url or "")
    return InferredLimitsResponse(
        max_steps=limits.max_steps,
        timeout_seconds=limits.timeout_seconds,
    )


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    recent_limit: int = Query(default=8, ge=1, le=50, alias="recentLimit"),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> DashboardStatsResponse:
    """返回仪表盘聚合统计。

    与分页列表解耦：COUNT 走 SQLite 索引，避免 dashboard 把"当前页"误当全量。
    """
    stats_or_err: Any
    status_snapshot_or_err: Any
    stats_or_err, status_snapshot_or_err = await asyncio.gather(
        run_in_thread(app.get_dashboard_stats, recent_limit=recent_limit),
        app.snapshot_queue_statuses(),
        return_exceptions=True,
    )
    if isinstance(stats_or_err, Exception):
        raise stats_or_err
    stats = stats_or_err
    status_snapshot: dict[str, str] = (
        {} if isinstance(status_snapshot_or_err, Exception) else status_snapshot_or_err
    )
    return DashboardStatsResponse(
        tasks_total=stats["tasks_total"],
        running_total=stats["running_total"],
        findings_total=stats["findings_total"],
        recent_tasks=[
            TaskSummaryResponse.from_task(task, scheduler_status=status_snapshot.get(task.task_id))
            for task in stats["recent_tasks"]
        ],
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """查询任务详情。"""
    task, sched = await app.get_task_with_scheduler(task_id)
    response = TaskResponse.from_task(task, scheduler_status=sched)
    if task.task_type == TaskType.WHITEBOX:
        latest = await run_in_thread(app.get_latest_analysis_run, task_id)
        if latest:
            response.latest_analysis_run = _build_analysis_run_summary(latest)
    return response


@router.post("/{task_id}/start", response_model=TaskStartResponse)
async def start_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskStartResponse:
    """将 pending 任务加入后台执行队列。"""
    task, sched = await _acall(app.start_task, task_id)
    return TaskStartResponse(
        scheduler_status=sched,
        task=TaskResponse.from_task(task, scheduler_status=sched),
    )


@router.post("/{task_id}/restart", response_model=TaskStartResponse)
async def restart_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskStartResponse:
    """重试失败/超时/取消的任务，创建新任务并立即入队。"""
    task, sched = await _acall(app.restart_task, task_id)
    return TaskStartResponse(
        scheduler_status=sched,
        task=TaskResponse.from_task(task, scheduler_status=sched),
    )


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """取消任务。支持 pending、queued 和 running 状态。"""
    task, sched = await _acall(app.cancel_task, task_id)
    return TaskResponse.from_task(task, scheduler_status=sched)


@router.post("/{task_id}/pause", response_model=TaskResponse)
async def pause_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """暂停运行中的任务。"""
    task = await _acall(app.pause_task, task_id)
    return TaskResponse.from_task(task)


@router.post("/{task_id}/resume", response_model=TaskResponse)
async def resume_task(
    task_id: TaskIdPath,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> TaskResponse:
    """恢复暂停的任务。"""
    task = await _acall(app.resume_task, task_id)
    return TaskResponse.from_task(task)


# ════════════════════════════════════════════════════════════════
# 分析执行（阶段二：白盒结果查询）
# ════════════════════════════════════════════════════════════════


def _build_source_location(row: dict[str, Any] | None) -> SourceLocationResponse | None:
    if not row or not row.get("source_file"):
        return None
    return SourceLocationResponse(
        file_path=row["source_file"],
        start_line=row.get("source_start_line", 1),
        start_column=row.get("source_start_column"),
        end_line=row.get("source_end_line"),
        end_column=row.get("source_end_column"),
    )


@router.get("/{task_id}/analysis-runs", response_model=AnalysisRunListResponse)
async def list_analysis_runs(
    task_id: TaskIdPath,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, gt=0, le=200),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> AnalysisRunListResponse:
    """列出任务的所有分析执行记录。"""
    runs, total = await run_in_thread(app.list_analysis_runs, task_id, offset=offset, limit=limit)
    # 批量取各 run 的投影计数与严重级别分布：此前对每个 run 串行执行 6+1 条
    # COUNT（N 个 run 最坏 N×7 条 SQL + 2N 次线程池往返），改为 IN GROUP BY
    # 一次取回，消除 analysis-runs 列表的 N+1 COUNT。
    analysis_ids = [run.analysis_id for run in runs]
    counts_map = await run_in_thread(app.get_analysis_counts_batch, analysis_ids)
    severity_map = await run_in_thread(app.get_analysis_finding_severity_counts_batch, analysis_ids)
    summaries: list[AnalysisRunSummaryResponse] = []
    for run in runs:
        summaries.append(
            _build_analysis_run_summary(
                run,
                counts=counts_map.get(run.analysis_id, {}),
                severity_counts=severity_map.get(run.analysis_id, {}),
            )
        )
    return AnalysisRunListResponse(
        items=summaries,
        total=total,
        has_more=(offset + limit) < total,
    )


@router.get(
    "/{task_id}/analysis-runs/{analysis_id}",
    response_model=AnalysisRunSummaryResponse,
)
async def get_analysis_run_summary(
    task_id: TaskIdPath,
    analysis_id: str,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> AnalysisRunSummaryResponse:
    """获取单次分析执行的摘要（含完整性结论和各类 count）。"""
    run = await _check_analysis_belongs(analysis_id, task_id, app)
    counts = await run_in_thread(app.get_analysis_counts, analysis_id)
    diag = await run_in_thread(app.get_analysis_diagnostics, analysis_id)
    severity_counts = await run_in_thread(app.get_analysis_finding_severity_counts, analysis_id)

    return _build_analysis_run_summary(
        run,
        counts=counts,
        severity_counts=severity_counts,
        metrics=_build_completeness_metrics(diag),
    )


@router.get(
    "/{task_id}/analysis-runs/{analysis_id}/endpoints",
    response_model=EndpointPageResponse,
)
async def list_analysis_endpoints(
    task_id: TaskIdPath,
    analysis_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, gt=0, le=200),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> EndpointPageResponse:
    """获取分析执行的端点列表（游标分页）。"""
    await _check_analysis_belongs(analysis_id, task_id, app)
    items, next_cursor, total, has_more = await run_in_thread(
        app.list_analysis_endpoints,
        analysis_id,
        cursor=cursor,
        limit=limit,
    )
    eps = [
        EndpointResponse(
            endpoint_id=ep["endpoint_id"],
            endpoint_fingerprint=ep["endpoint_fingerprint"],
            analysis_id=analysis_id,
            http_method=ep["http_method"],
            normalized_path=ep["normalized_path_template"],
            normalized_path_template=ep["normalized_path_template"],
            is_templated=ep.get("is_templated", False),
            path_segment_count=ep.get("path_segment_count", 1),
            controller_class=ep.get("controller_class"),
            controller_method=ep.get("controller_method"),
            parameters=ep.get("parameters", []),
            return_type=ep.get("return_type"),
            source_location=_build_source_location(ep),
            entry_call_node_id=ep.get("entry_call_node_id"),
        )
        for ep in items
    ]
    return EndpointPageResponse(
        items=eps,
        next_cursor=next_cursor,
        total=total,
        has_more=has_more,
    )


@router.get(
    "/{task_id}/analysis-runs/{analysis_id}/call-nodes",
    response_model=CallNodePageResponse,
)
async def list_analysis_call_nodes(
    task_id: TaskIdPath,
    analysis_id: str,
    class_name: str | None = Query(default=None, alias="className"),
    method_name: str | None = Query(default=None, alias="methodName"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, gt=0, le=200),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> CallNodePageResponse:
    """获取分析执行的调用图节点列表（支持类名/方法名搜索）。"""
    await _check_analysis_belongs(analysis_id, task_id, app)
    items, next_cursor, total, has_more = await run_in_thread(
        app.list_analysis_call_nodes,
        analysis_id,
        class_name=class_name,
        method_name=method_name,
        cursor=cursor,
        limit=limit,
    )
    nodes = [
        CallNodeResponse(
            call_node_id=cn["call_node_id"],
            call_node_fingerprint=cn["call_node_fingerprint"],
            class_name=cn["class_name"],
            method_name=cn["method_name"],
            method_signature=cn.get("method_signature"),
            source_location=_build_source_location(cn),
            callee_count=0,
        )
        for cn in items
    ]
    return CallNodePageResponse(
        items=nodes,
        next_cursor=next_cursor,
        total=total,
        has_more=has_more,
    )


@router.get(
    "/{task_id}/analysis-runs/{analysis_id}/call-graph",
    response_model=CallGraphPageResponse,
)
async def list_analysis_call_edges(
    task_id: TaskIdPath,
    analysis_id: str,
    entry_node_id: str | None = Query(default=None, alias="entryNodeId"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, gt=0, le=200),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> CallGraphPageResponse:
    """获取分析执行的调用图边列表（可按入口节点过滤）。"""
    await _check_analysis_belongs(analysis_id, task_id, app)
    items, next_cursor, total, has_more = await run_in_thread(
        app.list_analysis_call_edges,
        analysis_id,
        entry_node_id=entry_node_id,
        cursor=cursor,
        limit=limit,
    )
    edges = [
        CallEdgeResponse(
            call_edge_id=ce["call_edge_id"],
            from_node_id=ce["from_node_id"],
            to_node_id=ce["to_node_id"],
            to_class_name=ce.get("to_class_name"),
            to_method_name=ce.get("to_method_name"),
            resolution_type=ce.get("resolution_type") or "UNKNOWN",
            confidence=ce.get("confidence"),
            source_location=_build_source_location(ce),
        )
        for ce in items
    ]
    return CallGraphPageResponse(
        items=edges,
        next_cursor=next_cursor,
        total=total,
        has_more=has_more,
    )


@router.get(
    "/{task_id}/analysis-runs/{analysis_id}/execution-flows",
    response_model=ExecutionFlowPageResponse,
)
async def list_analysis_execution_flows(
    task_id: TaskIdPath,
    analysis_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, gt=0, le=200),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> ExecutionFlowPageResponse:
    """获取分析执行的执行流列表。"""
    await _check_analysis_belongs(analysis_id, task_id, app)
    items, next_cursor, total, has_more = await run_in_thread(
        app.list_analysis_execution_flows,
        analysis_id,
        cursor=cursor,
        limit=limit,
    )
    # 一次取全所有 flow steps 后按 execution_flow_id 分组，避免对每个 flow 单独
    # 查询（N+1）。steps 已按 execution_flow_id, step_index 排序（JOIN 查询）。
    steps_by_flow: dict[str, list[dict[str, Any]]] = {}
    if items:
        all_steps = await run_in_thread(app.list_all_analysis_flow_steps, analysis_id)
        for step in all_steps:
            steps_by_flow.setdefault(step["execution_flow_id"], []).append(step)
    flows = []
    for flow in items:
        flow_id = flow["execution_flow_id"]
        steps_raw = steps_by_flow.get(flow_id, [])
        steps = [
            ExecutionFlowStepResponse(
                flow_step_id=step["flow_step_id"],
                step_index=step["step_index"],
                depth=step.get("depth", 0),
                method_key=step["method_key"],
                class_name=step.get("class_name"),
                method_name=step.get("method_name"),
                call_node_id=step.get("call_node_id"),
            )
            for step in steps_raw
        ]
        flows.append(
            ExecutionFlowResponse(
                execution_flow_id=flow["execution_flow_id"],
                entry_point=flow["entry_point"],
                call_depth=flow.get("call_depth", 0),
                steps=steps,
            )
        )
    return ExecutionFlowPageResponse(
        items=flows,
        next_cursor=next_cursor,
        total=total,
        has_more=has_more,
    )


@router.get(
    "/{task_id}/analysis-runs/{analysis_id}/diagnostics",
    response_model=DiagnosticsResponse,
)
async def get_analysis_diagnostics(
    task_id: TaskIdPath,
    analysis_id: str,
    app: TaskApplicationService = Depends(get_task_app_service),
) -> DiagnosticsResponse:
    """获取分析执行的诊断详情。"""
    await _check_analysis_belongs(analysis_id, task_id, app)
    diag = await run_in_thread(app.get_analysis_diagnostics, analysis_id)
    if diag is None:
        raise HTTPException(status_code=404, detail="Diagnostics not found")
    return DiagnosticsResponse(
        total_source_files=diag["total_source_files"],
        eligible_source_files=diag["eligible_source_files"],
        parsed_file_count=diag["parsed_file_count"],
        failed_file_count=diag["failed_file_count"],
        failed_files=diag["failed_files"],
        total_calls=diag["total_calls"],
        resolved_high=diag["resolved_high"],
        resolved_medium=diag["resolved_medium"],
        resolved_low=diag["resolved_low"],
        unresolved=diag["unresolved"],
        classpath_available=diag["classpath_available"],
        jar_count=diag["jar_count"],
        classpath_source=diag["classpath_source"],
        classpath_warnings=diag["classpath_warnings"],
        classpath_errors=diag["classpath_errors"],
        module_count=diag["module_count"],
        application_module_count=diag["application_module_count"],
    )


@router.get(
    "/{task_id}/analysis-runs/{analysis_id}/clusters",
    response_model=ClusterPageResponse,
)
async def list_analysis_clusters(
    task_id: TaskIdPath,
    analysis_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> ClusterPageResponse:
    """查询分析执行的功能聚类（按 analysis_id 分页）。"""
    await _check_analysis_belongs(analysis_id, task_id, app)
    items, next_cursor, total, has_more = await run_in_thread(
        app.list_analysis_clusters, analysis_id, cursor=cursor, limit=limit
    )
    return ClusterPageResponse(
        items=[
            ClusterResponse(
                cluster_id=item["cluster_id"],
                suggested_label=item.get("suggested_label", ""),
                member_keys=item.get("member_keys", []),
                member_count=item.get("member_count", 0),
            )
            for item in items
        ],
        next_cursor=next_cursor,
        total=total,
        has_more=has_more,
    )


@router.get(
    "/{task_id}/analysis-runs/{analysis_id}/findings",
    response_model=FindingPageResponse,
)
async def list_analysis_findings(
    task_id: TaskIdPath,
    analysis_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    app: TaskApplicationService = Depends(get_task_app_service),
) -> FindingPageResponse:
    """查询分析执行的发现项（按 analysis_id 分页）。"""
    await _check_analysis_belongs(analysis_id, task_id, app)
    findings, next_cursor, total, has_more = await run_in_thread(
        app.get_analysis_findings, analysis_id, cursor=cursor, limit=limit
    )
    return FindingPageResponse(
        items=[
            FindingDetailResponse(
                finding_id=f.finding_id,
                title=f.title,
                description=f.description,
                severity=f.severity.value,
                finding_type=f.finding_type.value,
                location=f.location,
                rule_id=f.rule_id,
                rule_category=f.rule_category,
                confidence=f.confidence,
                snippet=f.snippet,
                analysis_id=f.analysis_id,
                created_at=f.created_at.isoformat() if f.created_at else "",
            )
            for f in findings
        ],
        next_cursor=next_cursor,
        total=total,
        has_more=has_more,
    )


async def _check_analysis_belongs(
    analysis_id: str,
    task_id: str,
    app: TaskApplicationService,
) -> Any:
    """校验 analysis_run 属于指定 task_id，通过后返回 run 对象（供调用方复用）。"""
    run = await run_in_thread(app.get_analysis_run, analysis_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    if run.task_id != task_id:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return run


def _build_completeness_metrics(diag: dict[str, Any] | None) -> CompletenessMetricsResponse:
    """从分析诊断 dict 构造完整性指标（无 diag 时回退全 0）。"""
    if diag:
        return CompletenessMetricsResponse(
            eligible_source_files=diag.get("eligible_source_files", 0),
            parsed_source_files=diag.get("parsed_file_count", 0),
            total_calls=diag.get("total_calls", 0),
            resolved_calls=(diag.get("resolved_high", 0) + diag.get("resolved_medium", 0)),
        )
    return CompletenessMetricsResponse(
        eligible_source_files=0, parsed_source_files=0, total_calls=0, resolved_calls=0
    )


def _build_analysis_run_summary(
    run: Any,
    *,
    counts: dict[str, Any] | None = None,
    severity_counts: dict[str, int] | None = None,
    metrics: CompletenessMetricsResponse | None = None,
) -> AnalysisRunSummaryResponse:
    """从 AnalysisRun 实体构造摘要响应。

    单次摘要（get_analysis_run_summary）与列表（list_analysis_runs）共用本函数：
    前者传入真实 counts / severity_counts / metrics，后者批量取数后同样传入，
    避免两处各自手工装配 quality_issues / completeness / count 字段导致漂移。
    """
    quality_issues: list[QualityIssueResponse] = [
        QualityIssueResponse(
            code=qi.code,
            level=qi.level,
            message=qi.message,
            affected_count=qi.affected_count if qi.affected_count is not None else None,
            total_count=qi.total_count if qi.total_count is not None else None,
        )
        for qi in (run.quality_issues or [])
    ]
    counts = counts or {}
    return AnalysisRunSummaryResponse(
        analysis_id=run.analysis_id,
        task_id=run.task_id,
        source_snapshot_id=run.source_snapshot_id,
        resolved_commit_sha=run.resolved_commit_sha,
        run_status=run.run_status,
        external_job_id=run.external_job_id,
        external_job_status=run.external_job_status,
        failure_code=run.failure_code,
        failure_message=run.failure_message,
        stop_reason=run.stop_reason,
        completeness=CompletenessResponse(
            status=run.completeness_status,
            issues=quality_issues,
            metrics=metrics
            or CompletenessMetricsResponse(
                eligible_source_files=0,
                parsed_source_files=0,
                total_calls=0,
                resolved_calls=0,
            ),
        ),
        endpoint_count=counts.get("analysis_endpoints", 0),
        call_graph_node_count=counts.get("analysis_call_nodes", 0),
        execution_flow_count=counts.get("analysis_execution_flows", 0),
        cluster_count=counts.get("analysis_clusters", 0),
        finding_count=counts.get("findings", 0),
        finding_severity_counts=severity_counts or {},
        created_at=run.created_at or "",
        started_at=run.started_at,
        completed_at=run.completed_at,
        projection_completed_at=run.projection_completed_at,
    )
