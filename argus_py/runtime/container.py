"""运行时容器：框架无关的组合根，直接构造子服务。

各消费者（FastAPI、CLI、Worker 独立进程）通过此容器
获取已装配好的服务实例，而不是自行组装。
关联编排的业务规则位于 ``argus_py.correlation.application``；
本模块只构造并注入依赖。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from argus_py.config.model_storage import ModelConfigSQLiteStorage
from argus_py.config.server_settings import ServerSettings, load_server_settings
from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskType
from argus_py.core.ids import generate_id
from argus_py.core.paths import LOGS_DIR
from argus_py.infra.db import set_default_pool_max_size
from argus_py.infra.events import EventBus
from argus_py.infra.queue import TaskQueue
from argus_py.infra.worker import TaskWorker
from argus_py.llm.client import set_llm_semaphore
from argus_py.observability.audit import AuditService, set_audit_service
from argus_py.observability.debug_bundle import DebugBundleBuilder
from argus_py.observability.diagnostics_service import DiagnosticsService
from argus_py.observability.diagnostics_store import FileDiagnosticsLogStore
from argus_py.observability.trace_reader import TraceReadService
from argus_py.project.service import ProjectService
from argus_py.project.storage import ProjectSQLiteStorage
from argus_py.report.generator import ReportGenerator
from argus_py.task.event import TaskTimelineService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.log import TaskLogService
from argus_py.task.read import TaskReadService
from argus_py.task.storage import TaskSQLiteStorage
from argus_py.whitebox.client import WhiteboxClient
from argus_py.whitebox.runner import WhiteboxRunner
from argus_py.whitebox.source_resolver import SourceResolver

if TYPE_CHECKING:
    from argus_py.correlation.application import CorrelationService
    from argus_py.regression.application import RegressionService
    from argus_py.task.application import TaskApplicationService

_TASK_HANDLER_TYPE = dict


def _build_path_mapping_from_settings(settings: ServerSettings) -> object | None:
    """从服务配置构造关联网关前缀映射；未配置时返回 None。

    延迟导入 PathMapping 以避免模块导入期循环依赖。
    """
    if (
        not settings.correlation_gateway_strip_prefixes
        and not settings.correlation_gateway_prepend_prefix
    ):
        return None
    from argus_py.correlation.models import PathMapping

    return PathMapping(
        strip_prefixes=list(settings.correlation_gateway_strip_prefixes),
        prepend_prefix=settings.correlation_gateway_prepend_prefix,
    )


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
    timeline_service: TaskTimelineService
    project_service: ProjectService
    model_config_service: ModelConfigService
    correlation_service: "CorrelationService"
    regression_service: "RegressionService"
    task_queue: TaskQueue
    task_worker: TaskWorker
    llm_semaphore: asyncio.Semaphore | None
    report_generator: ReportGenerator
    # 白盒
    whitebox_client: WhiteboxClient
    whitebox_runner: WhiteboxRunner
    source_resolver: SourceResolver
    # 诊断中心（方案第 17 章：仓储在组合根组装，route/service 不得自行创建）
    diagnostics_store: FileDiagnosticsLogStore
    diagnostics_service: DiagnosticsService
    diagnostics_semaphore: asyncio.Semaphore
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

    model_config_service = ModelConfigService(ModelConfigSQLiteStorage())
    task_queue = TaskQueue(max_size=settings.scheduler_queue_max_size)

    # ── 直接构造子服务 ──
    storage = TaskSQLiteStorage()

    lifecycle_service = TaskLifecycleService(storage, event_publisher=event_bus.publish)
    log_service = TaskLogService(storage, event_publisher=event_bus.publish)
    task_read_service = TaskReadService(storage)
    trace_reader_service = TraceReadService()
    debug_bundle_builder = DebugBundleBuilder()
    timeline_service = TaskTimelineService(storage, event_publisher=event_bus.publish)

    project_service = ProjectService(
        ProjectSQLiteStorage(),
        task_read_service=task_read_service,
    )

    # ── 白盒：SourceResolver ──
    source_resolver = SourceResolver(
        work_dir=settings.whitebox_source_work_dir,
        allowed_roots=[Path(p) for p in settings.whitebox_allowed_source_roots],
        # O-07：快照排除规则；留空使用保守默认集。
        exclude_dirs=(
            frozenset(settings.whitebox_snapshot_exclude_dirs)
            if settings.whitebox_snapshot_exclude_dirs
            else None
        ),
    )

    # ── 白盒：WhiteboxClient ──
    whitebox_client = WhiteboxClient(
        base_url=settings.java_analyzer_url,
        request_timeout=settings.java_analyzer_request_timeout,
    )

    # ── 关联编排：业务规则在 CorrelationService，组合根只装配依赖 ──
    from argus_py.blackbox.runner import BlackboxRunner
    from argus_py.correlation.application import CorrelationService

    # 关联网关前缀映射：任一前缀/重挂前缀非空时启用，否则恒 None（默认关闭）。
    # 注入 matcher 供匹配时对齐浏览器侧路径与后端端点；配置变更会体现在
    # correlation_config_digest（compute_config_digest 已含 strip_prefixes）。
    path_mapping = _build_path_mapping_from_settings(settings)

    # 报告生成器单例：初始生成与关联完成后重生成共用同一实例（相同输出路径）
    report_generator = ReportGenerator()

    # 生成 Worker 标识（单进程单 Worker，ID 稳定）
    worker_id = getattr(settings, "worker_id", "") or generate_id("w")

    correlation_service = CorrelationService(
        storage=storage,
        report_generator=report_generator,
        save_task=lifecycle_service.save_task,
        path_mapping=path_mapping,
        gateway_strip_prefixes=settings.correlation_gateway_strip_prefixes,
        gateway_prepend_prefix=settings.correlation_gateway_prepend_prefix,
        worker_id=worker_id,
    )

    whitebox_runner = WhiteboxRunner(
        client=whitebox_client,
        source_resolver=source_resolver,
        timeline_service=timeline_service,
        lifecycle=lifecycle_service,
        on_analysis_succeeded=correlation_service.on_whitebox_analysis_succeeded,
    )

    blackbox_runner = BlackboxRunner(
        lifecycle=lifecycle_service,
        reader=task_read_service,
        log_service=log_service,
        timeline_service=timeline_service,
        model_config_service=model_config_service,
        report_generator=report_generator,
        persist_request_batch=correlation_service.persist_request_batch,
        create_blackbox_run=correlation_service.create_blackbox_run,
        create_correlation_run=correlation_service.open_correlation_run,
        finalize_blackbox_run=correlation_service.finalize_blackbox_run,
        claim_and_execute_correlation=correlation_service.claim_and_execute,
        worker_id=worker_id,
    )

    # ── 回归测试闭环：批次协调（终态回调晚绑定到 lifecycle）──
    from argus_py.regression.application import RegressionService
    from argus_py.task.application import TaskApplicationService

    # resolve_create_params 是无状态的参数校验编排；这里构造一个仅供回归
    # 使用的 TaskApplicationService 实例来复用它（与 API 路由的实例互不影响）。
    task_app_for_regression = TaskApplicationService(
        lifecycle=lifecycle_service,
        task_read=task_read_service,
        queue=task_queue,
        project_service=project_service,
        model_config_service=model_config_service,
    )
    regression_service = RegressionService(
        storage=storage,
        lifecycle=lifecycle_service,
        queue=task_queue,
        resolve_create_params=task_app_for_regression.resolve_create_params,
        event_publisher=event_bus.publish,
    )
    lifecycle_service.set_task_terminal_callback(regression_service.handle_task_terminal)

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
        report_generator=report_generator,
        worker_id=worker_id,
        # O-04 启动恢复：启动时接管孤儿白盒作业（SUCCEEDED 拉结果 / RUNNING 重入队）
        whitebox_client=whitebox_client,
        # 回归批次崩溃恢复：对账非终态批次并收尾
        recover_regression_runs=regression_service.recover_stale_runs,
    )

    llm_semaphore = (
        asyncio.Semaphore(settings.llm_max_inflight) if settings.llm_max_inflight > 0 else None
    )
    if llm_semaphore is not None:
        set_llm_semaphore(llm_semaphore)

    # ── 诊断中心：文件日志仓储 + 服务状态聚合 + 查询并发闸门（方案第 17 章）──
    diagnostics_store = FileDiagnosticsLogStore(LOGS_DIR)
    diagnostics_store.set_scan_budget(settings.diagnostics_scan_max_bytes)
    diagnostics_semaphore = asyncio.Semaphore(settings.diagnostics_max_concurrent_queries)
    diagnostics_service = DiagnosticsService(settings, diagnostics_store)

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
        correlation_service=correlation_service,
        regression_service=regression_service,
        task_queue=task_queue,
        task_worker=task_worker,
        llm_semaphore=llm_semaphore,
        report_generator=report_generator,
        whitebox_client=whitebox_client,
        whitebox_runner=whitebox_runner,
        source_resolver=source_resolver,
        diagnostics_store=diagnostics_store,
        diagnostics_service=diagnostics_service,
        diagnostics_semaphore=diagnostics_semaphore,
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
