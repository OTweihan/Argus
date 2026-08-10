"""FastAPI 应用实例。"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from argus_py.api.auth import DEFAULT_PROTECTED_PREFIXES, AuthTokenMiddleware
from argus_py.api.dependencies import get_task_worker, reset_all_dependencies
from argus_py.api.middleware import configure_middleware
from argus_py.api.routes import (
    config,
    correlation,
    events,
    health,
    projects,
    prompts,
    reports,
    tasks,
    ws,
)
from argus_py.config.server_settings import ServerSettings, load_server_settings
from argus_py.config.settings import load_settings
from argus_py.core.constants import PROJECT_NAME, PROJECT_TAGLINE, PROJECT_VERSION
from argus_py.core.crypto import ensure_fernet_key
from argus_py.core.paths import API_STATIC_DIR, OUTPUT_DIR
from argus_py.infra.db import DEFAULT_DB_PATH, _DefaultDBProbe
from argus_py.infra.recovery import recover_interrupted_tasks
from argus_py.infra.singleton_lock import SingleInstanceLock
from argus_py.infra.temp_cleanup import cleanup_stale_debug_bundles
from argus_py.observability import (
    cleanup_old_traces,
    start_trace_writer,
    stop_trace_writer,
)
from argus_py.observability.context import set_io_executor
from argus_py.observability.events import STATUS_ERROR, log_event
from argus_py.runtime.container import create_container, shutdown_container
from argus_py.utils.logger import setup_logging

logger = logging.getLogger(__name__)

API_PREFIX = "/argus/api"
# 启用可选 API Token 鉴权的环境变量名。
# 未设置或为空字符串 → 中间件不挂载，向后兼容。
AUTH_TOKEN_ENV = "ARGUS_API_TOKEN"


def _raise_if_multi_worker() -> None:
    """检测到多 worker env 时直接抛启动错误（fail-closed）。

    CLI ``argus serve`` 会在更早一步拒启；这里兜底防止有人直接
    ``uvicorn argus_py.api.app:app --workers N`` 绕过 CLI。多 worker 下
    进程内任务队列与 EventBus 不跨进程共享，会出现任务双发和 WS 事件丢失，
    因此不只是告警——直接拒绝启动。
    """
    for env_name in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        raw = os.getenv(env_name)
        if not raw:
            continue
        try:
            count = int(raw)
        except ValueError:
            continue
        if count > 1:
            raise RuntimeError(
                f"检测到 {env_name}={count}，Argus 不支持多 worker 部署："
                "进程内任务队列与 EventBus 不跨进程共享，会出现任务双发和 WS 事件丢失。"
                "请改用单 worker，通过 config/server.yaml 的 scheduler.concurrency 调大并发。"
            )


def _warn_loose_source_roots(settings: ServerSettings) -> None:
    """Python 未配置本地源码输入 allowed roots 时给出宽松模式告警。

    allowed-source-roots 是对"本地路径分析输入"的边界约束。未配置时按宽松
    模式处理（Python 可读取并复制进程可见的任意本地目录），这是与旧行为兼容的
    过渡期；容器部署必须显式配置（compose 已强制 /tmp/sources）。Java 裸机默认
    仍只接受其临时快照目录，不会因 Python 侧宽松而直接分析任意 Java 可见目录。
    """
    if settings.whitebox_allowed_source_roots:
        return
    logger.warning(
        "whitebox.allowed_source_roots 未配置，Python 本地源码输入处于宽松模式"
        "（可读取并复制 Python 进程可见的任意目录）。容器/生产部署请设置"
        " ARGUS_WHITEBOX_ALLOWED_SOURCE_ROOTS 收紧到共享源码目录。"
    )


def create_app() -> FastAPI:
    """创建 FastAPI 应用并注册路由。"""
    setup_logging()
    settings = load_server_settings()
    load_settings().ensure_output_dirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """管理后台任务 Worker 与 LLM trace writer 生命周期。

        ``app.state.lifespan_ready`` 标记进程是否完成初始化：在 yield 前为
        False，``/ready`` 探针因此返回 503，避免把未就绪实例判为可用。

        单实例约束（O-02）：
        - 可识别的多 worker env（WEB_CONCURRENCY/UVICORN_WORKERS > 1）直接抛启动错误；
        - 启动时在 outputs 目录获取跨进程独占锁，拿不到说明已有实例指向同一份
          DB/outputs，同样拒绝启动。OS 文件锁随进程退出自动释放。
        """
        app.state.lifespan_ready = False
        _raise_if_multi_worker()
        _warn_loose_source_roots(settings)
        ensure_fernet_key(_DefaultDBProbe(DEFAULT_DB_PATH))
        lock = SingleInstanceLock(OUTPUT_DIR / ".argus-singleton.lock")
        if not lock.acquire(owner=f"pid={os.getpid()}; app={PROJECT_NAME}"):
            raise RuntimeError(
                "检测到已有 Argus 进程正在使用同一 outputs 目录，拒绝启动："
                f"{lock.lock_path}。Argus 强制单实例（进程内任务队列与 EventBus），"
                "请先停止旧进程或指定独立的 outputs 目录。"
            )
        try:
            c = create_container()
            app.state.container = c
            recover_interrupted_tasks(lifecycle=c.lifecycle_service, reader=c.task_read_service)
        except Exception:
            log_event(logger, "lifespan.recover_tasks", status=STATUS_ERROR, exc_info=True)
            lock.release()
            raise
        try:
            cleanup_stale_debug_bundles()
        except Exception:
            log_event(logger, "lifespan.cleanup_bundles", status=STATUS_ERROR, exc_info=True)
        if settings.llm_trace_enabled:
            try:
                cleanup_old_traces(
                    OUTPUT_DIR / "traces",
                    retention_days=settings.llm_trace_retention_days,
                    total_size_mb=settings.llm_trace_total_size_mb,
                )
            except Exception:
                log_event(logger, "lifespan.cleanup_traces", status=STATUS_ERROR, exc_info=True)
            if settings.llm_trace_async_writer:
                start_trace_writer(
                    max_queue_size=settings.llm_trace_writer_queue_size,
                    flush_interval_seconds=settings.llm_trace_writer_flush_interval,
                    batch_size=settings.llm_trace_writer_batch_size,
                )
        executor = ThreadPoolExecutor(
            max_workers=min(32, (os.cpu_count() or 1) * 4),
            thread_name_prefix="argus-io",
        )
        set_io_executor(executor)
        worker = get_task_worker()
        try:
            await worker.start()
            app.state.lifespan_ready = True
            yield
        finally:
            app.state.lifespan_ready = False
            try:
                await worker.stop(settings.scheduler_shutdown_timeout_seconds)
            finally:
                try:
                    # writer 先 stop 以 flush 残留 trace；超时与 worker 一致。
                    stop_trace_writer(timeout=settings.scheduler_shutdown_timeout_seconds)
                finally:
                    try:
                        await shutdown_container()
                    finally:
                        reset_all_dependencies()
                        set_io_executor(None)
                        executor.shutdown(wait=True, cancel_futures=True)
                        lock.release()

    application = FastAPI(
        title=f"{PROJECT_NAME} API",
        description=PROJECT_TAGLINE,
        version=PROJECT_VERSION,
        lifespan=lifespan,
    )
    configure_middleware(application, settings)

    auth_token = (os.getenv(AUTH_TOKEN_ENV) or "").strip()
    if auth_token:
        # token 中间件放在最末 add → 最外层执行：未通过校验时不消耗下游限流桶。
        application.add_middleware(AuthTokenMiddleware, token=auth_token)
        logger.info(
            "API Token 鉴权已启用（受保护前缀：%s）",
            ",".join(DEFAULT_PROTECTED_PREFIXES),
        )

    application.include_router(health.router)
    application.include_router(projects.router, prefix=API_PREFIX)
    application.include_router(tasks.router, prefix=API_PREFIX)
    application.include_router(reports.router, prefix=API_PREFIX)
    application.include_router(config.router, prefix=API_PREFIX)
    application.include_router(events.router, prefix=API_PREFIX)
    application.include_router(prompts.router, prefix=API_PREFIX)
    application.include_router(ws.router, prefix=API_PREFIX)
    application.include_router(correlation.router, prefix=API_PREFIX)
    if (API_STATIC_DIR / "index.html").exists():
        application.mount(
            "/",
            StaticFiles(directory=API_STATIC_DIR, html=True),
            name="console",
        )
    return application


app = create_app()
