"""运行时容器：框架无关的组合根，直接构造子服务。

各消费者（FastAPI、CLI、Worker 独立进程）通过此容器
获取已装配好的服务实例，而不是自行组装。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from argus_py.config.server_settings import ServerSettings, load_server_settings
from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskType
from argus_py.core.ids import generate_id
from argus_py.infra.db import set_default_pool_max_size
from argus_py.infra.events import EventBus
from argus_py.infra.queue import TaskQueue
from argus_py.infra.worker import TaskWorker
from argus_py.llm.client import set_llm_semaphore
from argus_py.observability.audit import AuditService, set_audit_service
from argus_py.observability.debug_bundle import DebugBundleBuilder
from argus_py.observability.trace_reader import TraceReadService
from argus_py.project.service import ProjectService
from argus_py.task.event import TaskTimelineService, _NullTimelineService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.log import TaskLogService
from argus_py.task.read import TaskReadService
from argus_py.task.storage import TaskSQLiteStorage
from argus_py.whitebox.client import WhiteboxClient
from argus_py.whitebox.runner import WhiteboxRunner
from argus_py.whitebox.source_resolver import SourceResolver

if TYPE_CHECKING:
    from argus_py.task.application import TaskApplicationService

_TASK_HANDLER_TYPE = dict


@dataclass(frozen=True)
class RuntimeContainer:
    """运行时容器：保存所有已初始化服务的引用。"""

    settings: ServerSettings
    event_bus: EventBus
    audit_service: AuditService
    lifecycle_service: TaskLifecycleService
    log_service: TaskLogService
    task_read_service: TaskReadService
    trace_reader_service: TraceReadService
    debug_bundle_builder: DebugBundleBuilder
    timeline_service: TaskTimelineService | _NullTimelineService
    project_service: ProjectService
    model_config_service: ModelConfigService
    task_queue: TaskQueue
    task_worker: TaskWorker
    llm_semaphore: asyncio.Semaphore | None
    # 白盒
    whitebox_client: WhiteboxClient
    whitebox_runner: WhiteboxRunner
    # 业务 handler 注册表（供测试/自定义注入）
    task_handlers: _TASK_HANDLER_TYPE


def create_task_application_service(
    container: RuntimeContainer,
) -> TaskApplicationService:
    """创建 TaskApplicationService，聚合容器中的子服务。"""
    from argus_py.task.application import TaskApplicationService

    return TaskApplicationService(
        lifecycle=container.lifecycle_service,
        task_read=container.task_read_service,
        queue=container.task_queue,
        project_service=container.project_service,
        model_config_service=container.model_config_service,
    )


@lru_cache
def create_container() -> RuntimeContainer:
    """创建（或返回已缓存的）运行时容器单例。

    注意：``@lru_cache`` 保证单例但可能会造成测试跨用例污染。测试中若直接调用此函数，
    务必在 teardown 中执行 ``create_container.cache_clear()`` 清除缓存。
    """
    settings = load_server_settings()

    set_default_pool_max_size(settings.db_pool_max_size)

    event_bus = EventBus(
        history_limit=settings.events_history_limit,
        subscriber_queue_size=settings.events_subscriber_queue_size,
        max_subscribers=settings.events_max_subscribers,
    )

    audit_service = AuditService(
        event_publisher=event_bus.publish if settings.observability_audit_logging else None,
    )
    set_audit_service(audit_service)

    model_config_service = ModelConfigService()
    task_queue = TaskQueue(max_size=settings.scheduler_queue_max_size)

    # ── 直接构造子服务 ──
    storage = TaskSQLiteStorage()

    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    lifecycle_service = TaskLifecycleService(storage, event_publisher=event_bus.publish)
    log_service = TaskLogService(storage, event_publisher=event_bus.publish)
    task_read_service = TaskReadService(storage)
    trace_reader_service = TraceReadService()
    debug_bundle_builder = DebugBundleBuilder()
    timeline_service = (
        TaskTimelineService(storage, event_publisher=event_bus.publish)
        if isinstance(storage, TaskSQLiteStorage)
        else _NullTimelineService()
    )

    project_service = ProjectService(task_read_service=task_read_service)

    # ── 白盒：SourceResolver ──
    source_resolver = SourceResolver(
        work_dir=settings.whitebox_source_work_dir,
        allowed_roots=[Path(p) for p in settings.whitebox_allowed_source_roots],
    )

    # ── 白盒：WhiteboxClient ──
    whitebox_client = WhiteboxClient(
        base_url=settings.java_analyzer_url,
        request_timeout=settings.java_analyzer_request_timeout,
    )

    # ── 白盒：WhiteboxRunner（延后创建，需要关联唤醒回调）──
    # (moved below correlation callbacks)

    # ── 黑盒：BlackboxRunner ──
    import uuid as _uuid

    from argus_py.blackbox.runner import BlackboxRunner
    from argus_py.correlation.enums import (
        BlackboxRunStatus,
        CorrelationEligibility,
        CorrelationRunStatus,
        RequestOutcome,
        RequestOwner,
    )
    from argus_py.correlation.models import BlackboxRun, CorrelationRun, HttpRequestEvidence
    from argus_py.correlation.path_utils import compute_config_digest

    # 关联回调 — 延迟绑定（storage 是 TaskSQLiteStorage）
    async def _correlation_persist_batch(
        batch: list[dict[str, Any]],
    ) -> None:
        """将由 BrowserSession 捕获的请求证据 dict 批量写入 DB。"""
        items: list[HttpRequestEvidence] = []
        for cap in batch:
            rid = f"hre:{_uuid.uuid4().hex[:12]}"
            items.append(
                HttpRequestEvidence(
                    request_evidence_id=rid,
                    blackbox_run_id=cap.get("blackbox_run_id", ""),
                    task_id=cap.get("task_id", ""),
                    step_execution_id=cap.get("step_execution_id"),
                    step_attempt=cap.get("step_attempt", 1),
                    request_sequence=cap.get("sequence", 0),
                    http_method=cap.get("method", "GET"),
                    normalized_path=cap.get("normalized_path", ""),
                    display_path=cap.get("display_path", ""),
                    origin=cap.get("origin", ""),
                    resource_type=cap.get("resource_type", "other"),
                    endpoint_match_eligibility=CorrelationEligibility(
                        cap.get("endpoint_match_eligibility", "CONFIRMED_ELIGIBLE")
                    ),
                    response_status=cap.get("response_status"),
                    outcome=RequestOutcome(cap.get("outcome", "COMPLETED")),
                    failure_code=cap.get("failure_code"),
                    request_owner=RequestOwner(cap.get("request_owner", "FRAME")),
                    response_from_service_worker=bool(
                        cap.get("response_from_service_worker", False)
                    ),
                    page_sequence=cap.get("page_sequence", 0),
                    captured_at=cap.get("started_at", ""),
                    finished_at=cap.get("finished_at"),
                )
            )
        storage.insert_http_request_batch(items)

    def _correlation_create_blackbox_run(task: Any) -> str:
        """创建 BlackboxRun 实例。"""
        run = BlackboxRun(
            blackbox_run_id=f"bbr:{_uuid.uuid4().hex[:12]}",
            task_id=task.task_id,
            attempt=task.execution_attempt,
            status=BlackboxRunStatus.RUNNING,
            started_at=_now_iso(),
        )
        storage.create_blackbox_run(run)
        return run.blackbox_run_id

    import logging as _logging

    _corr_logger = _logging.getLogger(__name__)

    def _correlation_create_correlation_run(
        blackbox_run_id: str,
        task: Any,
    ) -> dict[str, Any] | None:
        """创建 CorrelationRun（WAITING_ANALYSIS 或 WAITING_BLACKBOX）。"""
        digest = compute_config_digest("v1", "v1")
        snapshot_id = getattr(task, "source_resolved_commit_sha", None) or ""
        cr = CorrelationRun(
            correlation_run_id=f"cr:{_uuid.uuid4().hex[:12]}",
            project_id=task.project_id or "",
            blackbox_run_id=blackbox_run_id,
            desired_source_snapshot_id=snapshot_id,
            desired_analysis_config_digest=snapshot_id,
            correlation_config_digest=digest,
            matcher_version="v1",
            normalization_version="v1",
            status=CorrelationRunStatus.WAITING_ANALYSIS,
            created_at=_now_iso(),
        )
        # 尝试自动绑定同项目、同快照的已有分析
        project_id = task.project_id or ""
        if project_id:
            latest_analysis = storage.get_latest_succeeded_analysis_by_project(
                project_id, source_snapshot_id=snapshot_id or None
            )
            if latest_analysis is not None:
                cr.analysis_id = latest_analysis.analysis_id
                cr.bound_source_snapshot_id = (
                    getattr(latest_analysis, "resolved_commit_sha", None) or ""
                )
                cr.analysis_projection_version = 1
                cr.status = CorrelationRunStatus.WAITING_BLACKBOX
        try:
            storage.create_correlation_run(cr)
        except Exception:
            # 唯一索引冲突 → 同一 blackbox_run_id 已有关联，幂等跳过
            existing = storage.get_correlation_run_by_blackbox(blackbox_run_id)
            if existing is not None:
                return {
                    "correlationRunId": existing.correlation_run_id,
                    "correlation_run_id": existing.correlation_run_id,
                }
            _corr_logger.exception(
                "创建 CorrelationRun 失败: blackbox_run_id=%s",
                blackbox_run_id,
            )
            return None
        return {
            "correlationRunId": cr.correlation_run_id,
            "correlation_run_id": cr.correlation_run_id,
        }

    def _correlation_finalize_blackbox_run(
        blackbox_run_id: str,
        status: str,
        quality: Any = None,
    ) -> None:
        """更新 BlackboxRun 终态 + 持久化采集质量。"""
        storage.update_blackbox_run_status(blackbox_run_id, status, completed_at=_now_iso())
        if quality is not None:
            storage.upsert_capture_quality(quality)

    async def _correlation_claim_and_execute(
        correlation_run_id: str,
        worker_id: str,
    ) -> None:
        """CAS 认领 + 执行关联匹配。"""
        import logging

        _logger = logging.getLogger(__name__)

        # 黑盒已完成：若分析也已就绪则推进到 READY 再认领
        cr = storage.get_correlation_run(correlation_run_id)
        if cr is None:
            return
        if cr.status == CorrelationRunStatus.WAITING_ANALYSIS:
            return  # 分析尚未完成，等白盒回调触发
        if cr.status == CorrelationRunStatus.WAITING_BLACKBOX:
            storage.set_correlation_status(correlation_run_id, "READY")

        attempt = storage.claim_and_create_attempt(correlation_run_id, worker_id)
        if attempt is None:
            return
        try:
            await _execute_correlation(attempt)
        except Exception:
            _logger.exception("关联匹配失败: attempt=%s", attempt.correlation_attempt_id)
            from argus_py.correlation.enums import AttemptStatus, EvidenceCompleteness

            storage.complete_and_activate_attempt(
                attempt.correlation_attempt_id,
                AttemptStatus.FAILED,
                EvidenceCompleteness.PARTIAL,
            )

    async def _execute_correlation(attempt: Any) -> None:
        """执行端点匹配 + 调用流关联 + Finding 证据关联。

        根据采集质量和匹配结果决定 completeness 是 COMPLETE 还是 PARTIAL，
        并写入对应的 reasons 和 diagnostics。
        """
        from argus_py.correlation._execution import (
            assess_capture_quality,
            build_quality_reasons,
            generate_finding_evidence,
            generate_flows,
            resolve_completeness,
        )
        from argus_py.correlation.enums import (
            AttemptDiagnosticCode,
            AttemptStatus,
            EvidenceCompleteness,
        )
        from argus_py.correlation.matcher import EndpointMatcher
        from argus_py.correlation.models import (
            CorrelationAttemptDiagnostic,
        )

        cr = storage.get_correlation_run(attempt.correlation_run_id)
        if cr is None or cr.analysis_id is None:
            storage.complete_and_activate_attempt(
                attempt.correlation_attempt_id,
                AttemptStatus.FAILED,
                EvidenceCompleteness.PARTIAL,
            )
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

        # 加载白盒端点
        endpoints_result = storage.list_analysis_endpoints(cr.analysis_id, limit=10_000)
        endpoints = endpoints_result[0]
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
                AttemptStatus.PARTIAL
                if completeness == EvidenceCompleteness.PARTIAL
                else AttemptStatus.SUCCEEDED,
                completeness,
            )
            return

        matcher = EndpointMatcher(matcher_version="v1", normalization_version="v1")
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
        flows = generate_flows(storage, cr.analysis_id, result.evidence_list, endpoints)
        if flows:
            storage.insert_flows_batch(flows)

        # ── 生成 Finding 证据关联 ──
        finding_evidence_list, finding_links = generate_finding_evidence(
            storage,
            cr.analysis_id,
            attempt.correlation_attempt_id,
            result.evidence_list,
            endpoints,
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
            AttemptStatus.PARTIAL
            if completeness == EvidenceCompleteness.PARTIAL
            else AttemptStatus.SUCCEEDED,
            completeness,
        )

    # 生成 Worker 标识（单进程单 Worker，ID 稳定）
    worker_id = getattr(settings, "worker_id", "") or generate_id("w")

    # ── 白盒唤醒回调 ──
    async def _on_whitebox_analysis_succeeded(
        task_id: str,
        analysis_id: str,
    ) -> None:
        """白盒分析成功后：查找 WAITING_ANALYSIS 的 CorrelationRun 并触发关联。"""
        from argus_py.correlation.enums import BlackboxRunStatus

        analysis_run = storage.get_analysis_run(analysis_id)
        if analysis_run is None:
            return
        snapshot_id = getattr(analysis_run, "resolved_commit_sha", None) or ""
        if not snapshot_id:
            return  # 无源码快照信息，无法可靠绑定

        # 获取分析任务的项目 ID，用于匹配同项目关联运行
        analysis_project_id = ""
        task_header = storage.load_task_header(task_id)
        if task_header:
            analysis_project_id = task_header.get("project_id", "") or ""

        waiting = storage.find_waiting_correlations(
            snapshot_id, project_id=analysis_project_id or None
        )
        for cr in waiting:
            storage.bind_correlation_analysis(
                cr.correlation_run_id,
                analysis_id,
                snapshot_id,
                projection_version=1,
                alignment="UNVERIFIED",
            )
            # 检查黑盒是否也已完成；已完成则直接推进到 READY
            bb_run = storage.get_blackbox_run(cr.blackbox_run_id)
            bb_done = bb_run is not None and bb_run.status in (
                BlackboxRunStatus.SUCCESS,
                BlackboxRunStatus.FAILED,
                BlackboxRunStatus.CANCELLED,
                BlackboxRunStatus.TIMED_OUT,
            )
            if bb_done:
                storage.set_correlation_status(cr.correlation_run_id, "READY")
            else:
                storage.set_correlation_status(cr.correlation_run_id, "WAITING_BLACKBOX")
            # 尝试立即推进和认领
            claimed = storage.claim_and_create_attempt(cr.correlation_run_id, worker_id)
            if claimed:
                await _execute_correlation(claimed)

    # 重新创建白盒 runner，带上关联唤醒回调
    whitebox_runner = WhiteboxRunner(
        client=whitebox_client,
        source_resolver=source_resolver,
        timeline_service=timeline_service,
        lifecycle=lifecycle_service,
        on_analysis_succeeded=_on_whitebox_analysis_succeeded,
    )

    blackbox_runner = BlackboxRunner(
        lifecycle=lifecycle_service,
        reader=task_read_service,
        log_service=log_service,
        timeline_service=timeline_service,
        model_config_service=model_config_service,
        persist_request_batch=_correlation_persist_batch,
        create_blackbox_run=_correlation_create_blackbox_run,
        create_correlation_run=_correlation_create_correlation_run,
        finalize_blackbox_run=_correlation_finalize_blackbox_run,
        claim_and_execute_correlation=_correlation_claim_and_execute,
        worker_id=worker_id,
    )

    # ── Handler 装配 ──
    handlers: _TASK_HANDLER_TYPE = {
        TaskType.BLACKBOX: blackbox_runner.run,
        TaskType.WHITEBOX: whitebox_runner.run,
    }

    task_worker = TaskWorker(
        queue=task_queue,
        lifecycle=lifecycle_service,
        reader=task_read_service,
        handlers=handlers,
        concurrency=settings.scheduler_concurrency,
        model_config_service=model_config_service,
        worker_id=worker_id,
    )

    llm_semaphore = (
        asyncio.Semaphore(settings.llm_max_inflight) if settings.llm_max_inflight > 0 else None
    )
    if llm_semaphore is not None:
        set_llm_semaphore(llm_semaphore)

    return RuntimeContainer(
        settings=settings,
        event_bus=event_bus,
        audit_service=audit_service,
        lifecycle_service=lifecycle_service,
        log_service=log_service,
        task_read_service=task_read_service,
        trace_reader_service=trace_reader_service,
        debug_bundle_builder=debug_bundle_builder,
        timeline_service=timeline_service,
        project_service=project_service,
        model_config_service=model_config_service,
        task_queue=task_queue,
        task_worker=task_worker,
        llm_semaphore=llm_semaphore,
        whitebox_client=whitebox_client,
        whitebox_runner=whitebox_runner,
        task_handlers=handlers,
    )


async def shutdown_container() -> None:
    """优雅关闭容器持有的所有共享资源。

    包括：
    - WhiteboxClient HTTP 连接
    - Playwright 浏览器进程（若已启动）
    - 数据库连接池

    调用时机：Worker 停机、FastAPI lifespan shutdown、CLI 命令结束。
    安全可重入：未初始化的资源静默跳过。
    """
    from argus_py.browser.singleton import stop_shared_client
    from argus_py.infra.db import close_all_db_pools

    container = create_container()
    try:
        await container.whitebox_client.aclose()
    except Exception:
        pass
    await stop_shared_client()
    close_all_db_pools()
    create_container.cache_clear()
